"""Permission-checked, versioned writes for reusable filing configuration."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone
from audit.models import AuditEvent
from .catalog_models import Client, FormDefinition, ClientFilingProfile, CLIENT_FIELDS, FORM_FIELDS, PROFILE_FIELDS


def require_permission(actor, permission):
    if not actor or not actor.is_authenticated or not actor.is_active or not actor.has_perm(permission):
        raise PermissionDenied("You do not have permission to change this record.")


CONFIG = {
    Client: (CLIENT_FIELDS, "client"),
    FormDefinition: (FORM_FIELDS, "form_definition"),
    ClientFilingProfile: (PROFILE_FIELDS + ("client", "form_definition"), "client_filing_profile"),
}


@transaction.atomic
def create_record(*, model, actor, data):
    fields, subject = CONFIG[model]
    require_permission(actor, f"workorders.add_{model._meta.model_name}")
    if set(data) - set(fields):
        raise ValidationError("Only configuration source fields may be supplied.")
    if model is Client:
        from .contact_defaults import contact_for_client
        data = {**data, **contact_for_client(data.get('client_code'))}
    record = model(**data)
    record.save(_service_write=True, force_insert=True)
    AuditEvent.objects.create(actor=actor, kind=AuditEvent.Kind.CONFIG_CREATED, **{subject: record})
    return record


@transaction.atomic
def update_record(*, model, pk, actor, expected_version, changes):
    fields, subject = CONFIG[model]
    require_permission(actor, f"workorders.change_{model._meta.model_name}")
    if set(changes) - set(fields):
        raise ValidationError("Only configuration source fields may be supplied.")
    record = model.objects.select_for_update().get(pk=pk)
    if record.version != expected_version:
        raise ValidationError("This configuration changed. Reload before saving.")
    if model is Client:
        from .contact_defaults import contact_for_client
        changes = {**changes, **contact_for_client(changes.get('client_code', record.client_code))}
    before = {name: getattr(record, name) for name in fields}
    for name, value in changes.items():
        if model is ClientFilingProfile and name in {"client", "form_definition"} and value != before[name]:
            raise ValidationError("A profile's client and form cannot be reassigned. Create another profile.")
        if model is FormDefinition and name in {"definition_key", "form_code", "form_version"} and value != before[name]:
            raise ValidationError("A form's identity cannot be changed. Create another version.")
        setattr(record, name, value)
    record.full_clean()
    changed = sorted(name for name in fields if getattr(record, name) != before[name])
    if not changed:
        return record
    record.version += 1
    record.updated_at = timezone.now()
    values = {name: getattr(record, name) for name in fields}
    values.update(version=record.version, updated_at=record.updated_at)
    if models.QuerySet.update(model.objects.filter(pk=pk, version=expected_version), **values) != 1:
        raise ValidationError("This configuration changed. Reload before saving.")
    AuditEvent.objects.create(actor=actor, kind=AuditEvent.Kind.CONFIG_EDITED, changed_fields=changed, **{subject: record})
    return record
