"""Atomic work-order writes; SQLite updates compare the expected row version."""
from copy import deepcopy
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from audit.models import AuditEvent
from .catalog_models import CLIENT_FIELDS, FORM_FIELDS, PROFILE_FIELDS
from .catalog_services import require_permission
from .definitions import get_definition, validate_form_data
from .models import WorkOrder, WorkOrderSnapshot, ClientFilingProfile, snapshot_digest
from .statuses import WorkOrderStatus as Status
from .validators import safe_filename_component

EDITABLE_FIELDS = frozenset({"filing_year", "filing_month", "filing_quarter", "zero_filing", "zero_filing_approved", "form_data"})
TRANSITIONS = {Status.DRAFT: {Status.READY_TO_PREPARE}, Status.READY_TO_PREPARE: {Status.DRAFT}}


def _validate_input(data):
    if not isinstance(data, dict) or set(data) - EDITABLE_FIELDS:
        raise ValidationError("Only filing period, zero-filing confirmation, and form data may be supplied.")


def _sources(profile):
    client, form = profile.client, profile.form_definition
    for source in (client, form, profile):
        source.full_clean()
    data = {"schema_version": 1, "origin": "client_filing_profile"}
    for key, source, fields in (("client", client, CLIENT_FIELDS), ("form", form, FORM_FIELDS), ("profile", profile, PROFILE_FIELDS)):
        data[key] = {name: deepcopy(getattr(source, name)) for name in fields}
        data[key]["id"] = str(source.pk)
    return data, {"client": client.version, "form": form.version, "profile": profile.version}


def _active(profile):
    if not all((profile.is_active, profile.client.is_active, profile.form_definition.is_active)):
        raise ValidationError("The client, form, and filing profile must all be active.")


def _materialize(order, payload):
    client, form, profile = payload["client"], payload["form"], payload["profile"]
    order.legacy_client_reference = client["client_code"]
    order.client_name = client["trade_name"] or client["registered_name"]
    order.client_name_safe = safe_filename_component(order.client_name)
    for field in ("tin1", "tin2", "tin3", "tin4", "rdo_code", "registered_name", "registered_address", "zip_code", "telephone_number", "email_address", "line_of_business"):
        setattr(order, field, client[field])
    for field in ("form_code", "expected_form_number", "form_selection_text"):
        setattr(order, field, form[field])
    order.year_end_month = profile["year_end_month"]
    order.calendar_year = profile["calendar_or_fiscal"] == "CALENDAR"
    order.atc_code = order.form_data.get("atc_code", "")


def _snapshot(order, payload, versions, actor):
    payload = deepcopy(payload)
    payload["filing"] = {name: deepcopy(getattr(order, name)) for name in EDITABLE_FIELDS}
    revision = (order.snapshots.aggregate(value=models.Max("revision"))["value"] or 0) + 1
    snap = WorkOrderSnapshot(work_order=order, revision=revision, data=payload, source_versions=versions,
                             sha256=snapshot_digest(payload, versions), created_by=actor)
    snap.save(_service_write=True)
    order.current_snapshot = snap
    _materialize(order, payload)


def _persist(order, old_version):
    order.version = old_version + 1
    order.updated_at = timezone.now()
    order.full_clean()
    values = {field.attname: getattr(order, field.attname) for field in order._meta.concrete_fields if not field.primary_key}
    if models.QuerySet.update(WorkOrder.objects.filter(pk=order.pk, version=old_version), **values) != 1:
        raise ValidationError("This work order changed. Reload it before saving.")


def _load_current(pk, expected_version):
    order = WorkOrder.objects.select_for_update().get(pk=pk)
    if order.is_archived:
        raise ValidationError('Archived work orders are read-only.')
    if order.version != expected_version:
        raise ValidationError("This work order changed. Reload it before saving.")
    return order


@transaction.atomic
def create_work_order(*, actor, data, client_filing_profile_id, creation_request_id=None):
    require_permission(actor, "workorders.add_workorder")
    _validate_input(data)
    profile = ClientFilingProfile.objects.select_related("client", "form_definition").get(pk=client_filing_profile_id)
    _active(profile)
    payload, versions = _sources(profile)
    effective = deepcopy(profile.default_form_data)
    if profile.default_atc_code is not None:
        effective["atc_code"] = profile.default_atc_code
    supplied = data.get("form_data", {})
    if not isinstance(supplied, dict):
        raise ValidationError("Form data must be a JSON object.")
    effective.update(supplied)
    effective = validate_form_data(profile.form_definition.definition_key, effective, require_atc=bool(get_definition(profile.form_definition.definition_key)))
    order = WorkOrder(**{**data, "form_data": effective}, client=profile.client, client_filing_profile=profile, created_by=actor, creation_request_id=creation_request_id)
    order.save(_service_write=True, force_insert=True)
    _snapshot(order, payload, versions, actor)
    order.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor, kind=AuditEvent.Kind.CREATED, new_status=order.status)
    return order


@transaction.atomic
def edit_work_order(*, work_order_id, actor, expected_version, changes):
    require_permission(actor, "workorders.change_workorder")
    _validate_input(changes)
    order = _load_current(work_order_id, expected_version)
    if order.is_legacy_unlinked or not order.current_snapshot_id:
        raise ValidationError("Historical records must be explicitly linked and reviewed first.")
    if order.status not in {Status.DRAFT, Status.READY_TO_PREPARE}:
        raise ValidationError("A claimed or completed work order cannot be edited.")
    previous = {name: deepcopy(getattr(order, name)) for name in EDITABLE_FIELDS}
    for name, value in changes.items():
        setattr(order, name, value)
    old_status = order.status
    order.status = Status.DRAFT
    order.full_clean()
    changed = sorted(name for name in EDITABLE_FIELDS if getattr(order, name) != previous[name])
    if not changed:
        order.status = old_status
        return order
    _snapshot(order, order.current_snapshot.data, order.current_snapshot.source_versions, actor)
    _persist(order, expected_version)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor, kind=AuditEvent.Kind.EDITED,
                              old_status=old_status, new_status=order.status, changed_fields=changed)
    return order


@transaction.atomic
def refresh_work_order_snapshot(*, work_order_id, actor, expected_version):
    require_permission(actor, "workorders.change_workorder")
    order = _load_current(work_order_id, expected_version)
    if order.is_legacy_unlinked:
        raise ValidationError("Link the historical work order first.")
    if order.status not in {Status.DRAFT, Status.READY_TO_PREPARE}:
        raise ValidationError("A claimed or completed work order cannot be refreshed.")
    profile = ClientFilingProfile.objects.select_related("client", "form_definition").get(pk=order.client_filing_profile_id)
    _active(profile)
    payload, versions = _sources(profile)
    old_status = order.status
    order.status = Status.DRAFT
    order.zero_filing_approved = False
    _snapshot(order, payload, versions, actor)
    _persist(order, expected_version)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor, kind=AuditEvent.Kind.SNAPSHOT_REFRESHED,
                              old_status=old_status, new_status=order.status, changed_fields=["current_snapshot", "zero_filing_approved"])
    return order


def validate_readiness(order):
    if order.is_archived:
        raise ValidationError('Archived work orders cannot be prepared.')
    from automation_api.worker_services import xml_reserved
    if xml_reserved(order):
        raise ValidationError("A prepared work order already reserves this XML filename. Resolve that review before preparing the same return again.")
    if order.is_legacy_unlinked or not order.current_snapshot_id:
        raise ValidationError("Link and review this historical record before queuing.")
    profile = ClientFilingProfile.objects.select_related("client", "form_definition").get(pk=order.client_filing_profile_id)
    _active(profile)
    payload, versions = _sources(profile)
    definition = get_definition(profile.form_definition.definition_key)
    if not definition or not profile.form_definition.preparation_automation_available:
        raise ValidationError("Preparation automation is not available for this form/version.")
    snap = order.current_snapshot
    snap.full_clean()
    if snap.source_versions != versions or any(snap.data.get(key) != payload[key] for key in ("client", "form", "profile")):
        raise ValidationError("The source configuration changed. Explicitly refresh and review the snapshot before queuing.")
    if snap.data.get("filing") != {name: getattr(order, name) for name in EDITABLE_FIELDS}:
        raise ValidationError("Filing details do not match the reviewed snapshot.")
    if not order.zero_filing or not order.zero_filing_approved:
        raise ValidationError("Explicit zero-filing confirmation is required.")
    return definition.automation_key


def get_preparation_automation_key(order):
    order = WorkOrder.objects.get(pk=order.pk)
    if order.status != Status.READY_TO_PREPARE:
        raise ValidationError("The work order must be ready to prepare.")
    return validate_readiness(order)


@transaction.atomic
def transition_work_order(*, work_order_id, actor, expected_version, target):
    require_permission(actor, "workorders.change_workorder")
    order = _load_current(work_order_id, expected_version)
    if target not in TRANSITIONS.get(order.status, set()):
        raise ValidationError("This status transition is not enabled.")
    if target == Status.READY_TO_PREPARE:
        validate_readiness(order)
    old_status = order.status
    order.status = target
    _persist(order, expected_version)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor, kind=AuditEvent.Kind.STATUS_CHANGED,
                              old_status=old_status, new_status=target)
    return order


@transaction.atomic
def link_legacy_work_order(*, work_order_id, actor, expected_version, client_filing_profile_id, confirmed, form_data):
    require_permission(actor, "workorders.change_workorder")
    if confirmed is not True:
        raise ValidationError("Explicit review and confirmation are required to link historical data.")
    order = _load_current(work_order_id, expected_version)
    if not order.is_legacy_unlinked:
        raise ValidationError("This work order is already linked.")
    profile = ClientFilingProfile.objects.select_related("client", "form_definition").get(pk=client_filing_profile_id)
    _active(profile)
    if (order.form_code, order.expected_form_number) != (profile.form_definition.form_code, profile.form_definition.expected_form_number):
        raise ValidationError("Historical work orders must retain their original form/version.")
    payload, versions = _sources(profile)
    old_status = order.status
    order.client, order.client_filing_profile = profile.client, profile
    order.status, order.zero_filing, order.zero_filing_approved = Status.DRAFT, True, False
    order.form_data = validate_form_data(profile.form_definition.definition_key, form_data, require_atc=True)
    _snapshot(order, payload, versions, actor)
    _persist(order, expected_version)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor, kind=AuditEvent.Kind.LEGACY_LINKED,
                              old_status=old_status, new_status=order.status, changed_fields=["client", "client_filing_profile", "current_snapshot"])
    return order


@transaction.atomic
def create_and_queue_work_order(*, actor, data, client_filing_profile_id, request_id, source_versions):
    require_permission(actor, "workorders.add_workorder")
    require_permission(actor, "workorders.change_workorder")
    existing = WorkOrder.objects.filter(creation_request_id=request_id).first()
    if existing:
        if existing.created_by_id != actor.pk or str(existing.client_filing_profile_id) != str(client_filing_profile_id):
            raise ValidationError("This preparation request belongs to another filing.")
        return existing
    profile = ClientFilingProfile.objects.select_related("client", "form_definition").get(pk=client_filing_profile_id)
    _, versions = _sources(profile)
    if versions != source_versions:
        raise ValidationError("The client or filing settings changed. Reload this page and review them again.")
    order = create_work_order(actor=actor, data=data, client_filing_profile_id=profile.pk, creation_request_id=request_id)
    return transition_work_order(work_order_id=order.pk, actor=actor, expected_version=order.version, target=Status.READY_TO_PREPARE)
