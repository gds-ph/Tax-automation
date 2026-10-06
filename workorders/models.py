import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import validators
from .catalog_models import Client, FormDefinition, ClientFilingProfile
from .definitions import get_definition, validate_form_data, validate_period
from .model_support import ServiceModel
from .statuses import WorkOrderStatus

# Displayed in red: every state that stops a filing and needs a person to look.
FAILURE_DISPLAY_STATUSES = frozenset({
    'PREPARATION_FAILED_PDF_NOT_FOUND', 'PREPARATION_FAILED_XML_NOT_FOUND',
    'PROFILE_REVIEW_REQUIRED', 'FAILED_SYSTEM', 'FAILED_BUSINESS',
    'BLOCKED_NOT_APPROVED', 'WORK_ORDER_VERIFICATION_FAILED',
    'SAVED_RETURN_NOT_UNIQUE', 'SAVED_RETURN_ROW_NOT_FOUND', 'REJECTED',
})


class TaskNoticeRead(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    work_order = models.ForeignKey('WorkOrder', on_delete=models.CASCADE)
    token = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'work_order'], name='unique_task_notice_read')]


class RegistrationSetup(models.Model):
    """Provenance for an explicitly reviewed directory-to-taxpayer link."""
    folder = models.CharField(max_length=255, unique=True)
    client = models.OneToOneField(Client, on_delete=models.PROTECT, related_name='registration_setup')
    source_path = models.CharField(max_length=2000)
    source_sha256 = models.CharField(max_length=64)
    source_text = models.TextField()
    reviewed_forms = models.JSONField(default=list)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(default=timezone.now)


def prepared_pdf_upload_path(instance, filename):
    return f"work_orders/{instance.work_order_id}/{instance.review_pdf_filename}"


def snapshot_digest(data, source_versions):
    canonical = json.dumps({"data": data, "source_versions": source_versions}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WorkOrder(ServiceModel):
    Status = WorkOrderStatus
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order_id = models.CharField(max_length=48, unique=True, editable=False)
    creation_request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders", editable=False)
    client_filing_profile = models.ForeignKey(ClientFilingProfile, on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders")
    current_snapshot = models.ForeignKey("WorkOrderSnapshot", on_delete=models.PROTECT, null=True, blank=True, related_name="current_for_orders", editable=False)
    filing_year = models.CharField(max_length=4, validators=[validators.filing_year])
    filing_month = models.PositiveSmallIntegerField(null=True, blank=True)
    filing_quarter = models.PositiveSmallIntegerField(null=True, blank=True, choices=[(q, str(q)) for q in range(1, 5)])
    zero_filing = models.BooleanField(default=False)
    zero_filing_approved = models.BooleanField(default=False)
    form_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=40, choices=Status.choices, default=Status.DRAFT, editable=False, db_index=True)
    is_archived = models.BooleanField(default=False, editable=False, db_index=True)

    # Materialized snapshot columns retained for historical records and existing
    # displays. These are never editable source inputs for new work orders.
    legacy_client_reference = models.CharField(max_length=100, blank=True, editable=False)
    client_name = models.CharField(max_length=200, blank=True, editable=False)
    client_name_safe = models.CharField(max_length=110, blank=True, editable=False)
    tin1 = models.CharField(max_length=3, blank=True, editable=False)
    tin2 = models.CharField(max_length=3, blank=True, editable=False)
    tin3 = models.CharField(max_length=3, blank=True, editable=False)
    tin4 = models.CharField(max_length=5, blank=True, editable=False)
    rdo_code = models.CharField(max_length=3, blank=True, editable=False)
    registered_name = models.CharField(max_length=200, blank=True, editable=False)
    registered_address = models.TextField(max_length=2000, blank=True, editable=False)
    zip_code = models.CharField(max_length=20, blank=True, editable=False)
    telephone_number = models.CharField(max_length=50, blank=True, editable=False)
    email_address = models.EmailField(blank=True, editable=False)
    line_of_business = models.CharField(max_length=200, blank=True, editable=False)
    form_code = models.CharField(max_length=20, blank=True, editable=False)
    form_selection_text = models.CharField(max_length=100, blank=True, editable=False)
    expected_form_number = models.CharField(max_length=30, blank=True, editable=False)
    year_end_month = models.CharField(max_length=2, blank=True, editable=False)
    calendar_year = models.BooleanField(default=True, editable=False)
    atc_code = models.CharField(max_length=30, blank=True, editable=False)
    prepared_pdf = models.FileField(upload_to=prepared_pdf_upload_path, max_length=300, blank=True, editable=False)
    prepared_pdf_sha256 = models.CharField(max_length=64, blank=True, validators=[validators.sha256_hex], editable=False)
    prepared_pdf_vm_path = models.CharField(max_length=500, blank=True, editable=False)
    saved_xml_path = models.CharField(max_length=500, blank=True, editable=False, help_text="Automation-VM-local metadata, never opened by Django.")
    page1_path = models.CharField(max_length=500, blank=True, editable=False)
    page2_path = models.CharField(max_length=500, blank=True, editable=False)
    preparation_status_output = models.CharField(max_length=40, blank=True, editable=False)
    submission_status = models.CharField(max_length=40, blank=True, editable=False)
    error_code = models.CharField(max_length=100, blank=True, editable=False)
    error_message = models.TextField(blank=True, editable=False)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    leased_at = models.DateTimeField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    agent_name = models.CharField(max_length=100, blank=True, editable=False)
    attempt_count = models.PositiveIntegerField(default=0, editable=False)
    approved_for_submission = models.BooleanField(default=False, editable=False)
    approval_id = models.CharField(max_length=100, blank=True, editable=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_work_orders", editable=False)
    approval_timestamp = models.DateTimeField(null=True, blank=True, editable=False)
    approval_comment = models.TextField(blank=True, editable=False)
    approved_pdf_sha256 = models.CharField(max_length=64, blank=True, validators=[validators.sha256_hex], editable=False)
    version = models.PositiveIntegerField(default=1, editable=False)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='assigned_work_orders', editable=False)
    assignment_version = models.PositiveIntegerField(default=0, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_work_orders", editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)


    class Meta:
        ordering = ["-created_at", "id"]
        permissions = [("view_prepared_pdf", "Can download protected prepared PDF")]
        constraints = [
            models.CheckConstraint(condition=~Q(status="AWAITING_SUBMISSION_APPROVAL") | (~Q(prepared_pdf="") & ~Q(prepared_pdf_sha256="") & ~Q(saved_xml_path="") & ~Q(prepared_pdf_vm_path="")), name="wo_review_requires_pdf_xml"),
            models.CheckConstraint(condition=Q(filing_quarter__isnull=True) | Q(filing_quarter__gte=1, filing_quarter__lte=4), name="wo_valid_quarter"),
            models.CheckConstraint(condition=Q(filing_month__isnull=True) | Q(filing_month__gte=1, filing_month__lte=12), name="wo_valid_month"),
            models.CheckConstraint(condition=Q(filing_month__isnull=True) | Q(filing_quarter__isnull=True), name="wo_one_period_granularity"),
            models.CheckConstraint(condition=Q(client__isnull=True, client_filing_profile__isnull=True) | Q(client__isnull=False, client_filing_profile__isnull=False), name="wo_client_profile_pair"),
            models.CheckConstraint(condition=Q(status__in=["CANCELLED", "DRAFT", "READY_TO_PREPARE", "PROCESSING_PREPARATION", "AWAITING_SUBMISSION_APPROVAL", "PREPARATION_FAILED_PDF_NOT_FOUND", "PREPARATION_FAILED_XML_NOT_FOUND", "PROFILE_REVIEW_REQUIRED", "FAILED_SYSTEM", "FAILED_BUSINESS"]), name="wo_m2_enabled_statuses"),
            models.CheckConstraint(condition=~Q(status="READY_TO_PREPARE") | Q(zero_filing_approved=True), name="wo_ready_requires_zero_confirmation"),
            models.CheckConstraint(condition=Q(approved_for_submission=False), name="wo_m2_no_submission_approval"),
            models.CheckConstraint(condition=Q(version__gte=1), name="wo_positive_version"),
        ]

    @property
    def is_legacy_unlinked(self):
        return self.client_filing_profile_id is None

    @property
    def combined_tin(self):
        return self.tin1 + self.tin2 + self.tin3 + self.tin4

    def _naming_definition(self):
        if self.current_snapshot_id and not self.is_legacy_unlinked:
            return get_definition(self.current_snapshot.data.get("form", {}).get("definition_key", ""))
        from .definitions import DEFINITIONS
        return next((definition for definition in DEFINITIONS.values()
                     if definition.expected_form_number == self.expected_form_number), None)

    @property
    def expected_return_period(self):
        definition = self._naming_definition()
        return definition.return_period(self) if definition else ""

    @property
    def expected_saved_return_name(self):
        definition = self._naming_definition()
        return definition.saved_return_name(self) if definition else ""

    @property
    def expected_xml_filename(self):
        return self.expected_saved_return_name + ".xml" if self.expected_saved_return_name else ""

    @property
    def review_pdf_filename(self):
        period = f'{self.filing_month:02d}' if self.filing_month is not None else f'Q{self.filing_quarter}'
        return f"{self.client_name_safe}_{self.form_code}_{self.filing_year}_{period}_COMPLETE.pdf"

    @property
    def period_label(self):
        return (f'{self.filing_month:02d}/{self.filing_year}' if self.filing_month is not None
                else f'Q{self.filing_quarter} {self.filing_year}')

    @property
    def live_submission_available(self):
        return self.expected_form_number == '2551Qv2018' or (
            self.expected_form_number == '1601Cv2018' and getattr(settings, 'ENABLE_1601C_SUBMISSION', False)) or (
            self.expected_form_number == '1601EQ' and getattr(settings, 'ENABLE_1601EQ_SUBMISSION', False)) or (
            self.expected_form_number == '0619F' and getattr(settings, 'ENABLE_0619F_SUBMISSION', False)) or (
            self.expected_form_number == '1600VTv2018' and getattr(settings, 'ENABLE_1600VT_SUBMISSION', False))

    @property
    def automation_key(self):
        if not self.current_snapshot_id or self.is_legacy_unlinked:
            return ""
        return self.current_snapshot.data.get("form", {}).get("automation_key", "")

    def clean_fields(self, exclude=None):
        if not isinstance(self.filing_year, str):
            raise ValidationError({"filing_year": "Supply the year as four-digit text."})
        if not self.work_order_id and self._state.adding:
            self.work_order_id = f"WO-{timezone.localdate().year}-{self.id.hex}"
        super().clean_fields(exclude=exclude)

    def clean(self):
        if bool(self.client_id) != bool(self.client_filing_profile_id):
            raise ValidationError("Client and filing profile must both be supplied.")
        if self.client_filing_profile_id and self.client_filing_profile.client_id != self.client_id:
            raise ValidationError("The filing profile does not belong to this client.")
        if self.current_snapshot_id and self.current_snapshot.work_order_id != self.pk:
            raise ValidationError("The snapshot belongs to a different work order.")
        if self.current_snapshot_id:
            form = self.current_snapshot.data.get("form", {})
        elif self.client_filing_profile_id:
            source = self.client_filing_profile.form_definition
            form = {"definition_key": source.definition_key, "filing_frequency": source.filing_frequency}
        else:
            form = {"definition_key": "", "filing_frequency": "QUARTERLY"}
        validate_period(form["filing_frequency"], self.filing_year, self.filing_month, self.filing_quarter)
        definition = get_definition(form.get("definition_key", ""))
        if not self.is_legacy_unlinked:
            self.form_data = validate_form_data(form.get("definition_key", ""), self.form_data, require_atc=bool(definition))
            if definition:
                definition.validate_zero(self.zero_filing)
        from automation_api.worker_policy import ENABLED_STATUSES
        if self.status not in ENABLED_STATUSES and not (self.status == 'CANCELLED' and self.is_archived):
            raise ValidationError("This status is not enabled yet.")
        if self.status == self.Status.READY_TO_PREPARE:
            if self.is_legacy_unlinked or not self.current_snapshot_id:
                raise ValidationError("Link and review this historical work order before queuing.")
            if not definition or not self.zero_filing_approved:
                raise ValidationError("A tested automation definition and explicit zero-filing confirmation are required.")
            from .services import validate_readiness
            validate_readiness(self)
        if any(getattr(self, name) for name in (
            "submission_status", "approved_for_submission", "approval_id", "approved_by_id", "approval_timestamp",
            "approval_comment", "approved_pdf_sha256", "page1_path", "page2_path",
        )):
            raise ValidationError("Submission and approval operations remain disabled.")
        if self.status in {self.Status.DRAFT, self.Status.READY_TO_PREPARE}:
            if any(getattr(self, name) for name in ("prepared_pdf", "prepared_pdf_sha256", "prepared_pdf_vm_path", "saved_xml_path",
                    "preparation_status_output", "lease_token", "leased_at", "lease_expires_at", "agent_name", "error_code", "error_message")):
                raise ValidationError("Draft/ready orders cannot contain preparation results or a lease.")
            if self.attempt_count and (self.preparation_attempts.count() != self.attempt_count or
                    self.preparation_attempts.exclude(state__in=['FAILED', 'ABANDONED']).exists()):
                raise ValidationError("Queued retries must retain only completed failed preparation attempts.")
        elif self.status != self.Status.CANCELLED:
            if not self.current_snapshot_id or not self.lease_token or not self.lease_expires_at or not self.agent_name or self.attempt_count < 1:
                raise ValidationError("Preparation states require a snapshot and assigned lease.")
        if bool(self.prepared_pdf) != bool(self.prepared_pdf_sha256):
            raise ValidationError("A prepared PDF and its digest must be recorded together.")
        if self.status == self.Status.AWAITING_SUBMISSION_APPROVAL:
            if not all((self.prepared_pdf, self.prepared_pdf_sha256, self.saved_xml_path, self.prepared_pdf_vm_path)):
                raise ValidationError("Both a protected PDF and the saved XML result are required.")
            if self.preparation_status_output != self.Status.AWAITING_SUBMISSION_APPROVAL:
                raise ValidationError("A successful preparation result is required.")

    def _operational(self):
        """The displayed state and its badge tone, decided together so the label
        and the colour can never disagree. A finished run is green; the label,
        not the colour, is what says whether the receipt was simulated."""
        approval = getattr(self, 'stage2_approval', None)
        receipt = getattr(approval, 'receipt_check', None) if approval else None
        if receipt and receipt.finalized_at:
            from email.utils import parseaddr
            sender = parseaddr(receipt.evidence.get('message', {}).get('from', ''))[1].lower()
            if sender != 'ebirforms-noreply@bir.gov.ph':
                return 'Simulation complete - package generated', 'success'
            return 'Receipt package generated', 'success'
        if receipt and receipt.received_at:
            return 'BIR receipt confirmation received', 'success'
        if receipt and receipt.trrc_escalation_sent_at:
            return 'TRRC escalation sent - awaiting BIR response', 'warn'
        if approval and approval.state == 'MANUALLY_SUBMITTED_UNVERIFIED':
            return 'Manually submitted - BIR confirmation unverified', 'warn'
        if approval and approval.submission_enabled:
            labels = {'QUEUED': 'Submission queued', 'RUNNING': 'Submission in progress',
                      'SUBMITTED_WAITING_FOR_CONFIRMATION': 'Submitted - awaiting BIR confirmation',
                      'SUBMISSION_UNCONFIRMED': 'Submission unconfirmed - operator review required',
                      'FAILED_SYSTEM': 'Stage 2 stopped - operator review required',
                      'ABANDONED': 'Stage 2 stopped after operator review'}
            tones = {'QUEUED': 'info', 'RUNNING': 'info',
                     'SUBMITTED_WAITING_FOR_CONFIRMATION': 'warn',
                     'APPROVED_READY_TO_SUBMIT': 'info',
                     'SUBMISSION_UNCONFIRMED': 'danger', 'FAILED_SYSTEM': 'danger', 'ABANDONED': 'danger',
                     'BLOCKED_NOT_APPROVED': 'danger', 'WORK_ORDER_VERIFICATION_FAILED': 'danger',
                     'SAVED_RETURN_NOT_UNIQUE': 'danger', 'SAVED_RETURN_ROW_NOT_FOUND': 'danger'}
            return (labels.get(approval.state, approval.state.replace('_', ' ').title()),
                    tones.get(approval.state, 'warn'))
        return self.get_status_display(), {
            'DRAFT': 'subtle', 'READY_TO_PREPARE': 'info', 'PROCESSING_PREPARATION': 'info',
            'AWAITING_SUBMISSION_APPROVAL': 'warn',
        }.get(self.status, 'danger' if self.status in FAILURE_DISPLAY_STATUSES else 'subtle')

    @property
    def operational_status(self):
        return self._operational()[0]

    @property
    def operational_tone(self):
        return self._operational()[1]

    def __str__(self):
        return self.work_order_id or str(self.id)


class WorkOrderSnapshot(ServiceModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="snapshots")
    revision = models.PositiveIntegerField()
    data = models.JSONField()
    source_versions = models.JSONField(default=dict, blank=True)
    sha256 = models.CharField(max_length=64, validators=[validators.sha256_hex], editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("work_order", "revision")
        constraints = [models.UniqueConstraint(fields=("work_order", "revision"), name="snapshot_unique_revision"),
                       models.CheckConstraint(condition=Q(revision__gte=1), name="snapshot_positive_revision")]

    def clean(self):
        if not isinstance(self.data, dict) or not isinstance(self.source_versions, dict):
            raise ValidationError("Snapshot contents must be JSON objects.")
        if self.sha256 != snapshot_digest(self.data, self.source_versions):
            raise ValidationError("The snapshot content does not match its SHA-256 digest.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Snapshots are immutable. Create a new revision.")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.work_order_id} / snapshot {self.revision}"


class RegistrationCardScan(models.Model):
    """Persistent, unreviewed extraction; never authorizes a filing."""
    folder = models.CharField(max_length=500, unique=True)
    status = models.CharField(max_length=20, default='PENDING')
    preferred_sha256 = models.CharField(max_length=64, blank=True)
    selection_note = models.CharField(max_length=500, blank=True)
    documents = models.JSONField(default=list)
    message = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class SavedCompany(models.Model):
    """Per-user shortcut to a company. Saving only pins it in that user's list;
    it never grants, limits or changes access for anyone."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_companies')
    # Either a configured client or a directory folder that has no client yet.
    client = models.ForeignKey(Client, on_delete=models.CASCADE, null=True, blank=True, related_name='saved_by')
    folder = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ('-created_at', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('user', 'client'), condition=Q(client__isnull=False), name='saved_unique_client'),
            models.UniqueConstraint(fields=('user', 'folder'), condition=~Q(folder=''), name='saved_unique_folder'),
            models.CheckConstraint(condition=(Q(client__isnull=False) & Q(folder='')) | (Q(client__isnull=True) & ~Q(folder='')),
                                   name='saved_exactly_one_target'),
        ]

    def __str__(self):
        return self.folder or str(self.client_id)
