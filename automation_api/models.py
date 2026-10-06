import hashlib
import secrets
import uuid
import base64
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from workorders.validators import sha256_hex


class PreparedReturnArchive(models.Model):
    """Durable, independently retried copy of the verified review PDF."""
    work_order = models.OneToOneField('workorders.WorkOrder', on_delete=models.PROTECT,
                                     related_name='prepared_return_archive')
    sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=12, default='PENDING', choices=[
        (value, value) for value in ('PENDING', 'RETRY', 'SAVED', 'BLOCKED')])
    next_attempt_at = models.DateTimeField(default=timezone.now)
    saved_at = models.DateTimeField(null=True, blank=True)
    path = models.CharField(max_length=1000, blank=True)
    error = models.CharField(max_length=500, blank=True)


class AgentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use automation_api.services for audited agent changes.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use automation_api.services for audited agent creation.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use automation_api.services for audited agent changes.")

    def delete(self):
        raise ValidationError("Disable agents instead of deleting their history.")


class Agent(models.Model):
    """Worker identity with a digest of a generated high-entropy bearer token.

    Authenticates the Stage 1 polling API; tokens are never stored in plaintext.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    token_hash = models.CharField(max_length=64, unique=True, validators=[sha256_hex], editable=False)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    token_rotated_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = AgentQuerySet.as_manager()

    def check_token(self, raw_token: str) -> bool:
        if not self.is_active or not isinstance(raw_token, str) or not raw_token:
            return False
        digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        return secrets.compare_digest(self.token_hash, digest)

    def save(self, *args, _service_write=False, **kwargs):
        if not _service_write:
            raise ValidationError("Use automation_api.services for audited agent changes.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Disable agents instead of deleting their history.")

    def __str__(self):
        return self.name


from workorders.model_support import ServiceModel


class PreparationAttempt(ServiceModel):
    class State(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        ABANDONED = "ABANDONED", "Abandoned after operator review"

    # Worker-generated request UUID makes claim delivery retryable without rerunning.
    id = models.UUIDField(primary_key=True, editable=False)
    work_order = models.ForeignKey("workorders.WorkOrder", on_delete=models.PROTECT, related_name="preparation_attempts")
    snapshot = models.ForeignKey("workorders.WorkOrderSnapshot", on_delete=models.PROTECT)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="preparation_attempts")
    lease_token = models.UUIDField(default=uuid.uuid4, editable=False)
    lease_expires_at = models.DateTimeField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.RUNNING)
    execution_slot = models.PositiveSmallIntegerField(null=True, blank=True, unique=True, default=1)
    result_digest = models.CharField(max_length=64, blank=True, validators=[sha256_hex])
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("started_at", "id")
        constraints = [
            models.CheckConstraint(condition=(models.Q(state="RUNNING", execution_slot=1, completed_at__isnull=True)
                | models.Q(state__in=["SUCCEEDED", "FAILED", "ABANDONED"], execution_slot__isnull=True, completed_at__isnull=False)), name="attempt_valid_state_slot"),
            models.UniqueConstraint(fields=("work_order",), condition=models.Q(state="RUNNING"), name="one_active_attempt_per_order"),
        ]

    def clean(self):
        if self.snapshot_id and self.work_order_id and self.snapshot.work_order_id != self.work_order_id:
            raise ValidationError("The attempt snapshot must belong to the work order.")

    def __str__(self):
        return f"{self.work_order_id} / {self.state}"


class CancellationCleanup(ServiceModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.OneToOneField('workorders.WorkOrder', on_delete=models.PROTECT, related_name='cancellation_cleanup')
    attempt = models.ForeignKey(PreparationAttempt, on_delete=models.PROTECT)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT)
    state = models.CharField(max_length=12, default='PENDING', choices=[(s, s) for s in ('PENDING', 'RUNNING', 'DONE', 'FAILED')])
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    archive_path = models.CharField(max_length=1000, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    error = models.CharField(max_length=500, blank=True)


class Stage2Approval(ServiceModel):
    """Snapshot-bound Stage 2 approval; older approvals remain rehearsal-only."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.OneToOneField('workorders.WorkOrder', on_delete=models.PROTECT, related_name='stage2_approval')
    snapshot = models.ForeignKey('workorders.WorkOrderSnapshot', on_delete=models.PROTECT)
    approved_by = models.ForeignKey('auth.User', on_delete=models.PROTECT)
    approved_at = models.DateTimeField(default=timezone.now)
    pdf_sha256 = models.CharField(max_length=64, validators=[sha256_hex])
    comment = models.TextField(blank=True)
    submission_enabled = models.BooleanField(default=False)
    success_screenshot = models.CharField(max_length=300, blank=True)
    success_screenshot_sha256 = models.CharField(max_length=64, blank=True, validators=[sha256_hex])
    state = models.CharField(max_length=40, default='QUEUED')
    attempt = models.OneToOneField(PreparationAttempt, null=True, blank=True, on_delete=models.PROTECT, related_name='stage2_approval')

    class Meta:
        permissions = [('approve_stage2', 'Can approve Stage 2 revalidation')]


class BirReceiptCheck(models.Model):
    """Durable polling schedule and receipt evidence, separate from VM execution results."""
    approval = models.OneToOneField(Stage2Approval, on_delete=models.PROTECT, related_name='receipt_check')
    filename = models.CharField(max_length=200)
    submitted_after = models.DateTimeField()
    next_check_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=250, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    message_id = models.CharField(max_length=100, blank=True, db_index=True)
    evidence = models.JSONField(default=dict, blank=True)
    confirmation_pdf = models.CharField(max_length=300, blank=True)
    final_package = models.CharField(max_length=300, blank=True)
    final_package_sha256 = models.CharField(max_length=64, blank=True, validators=[sha256_hex])
    finalized_at = models.DateTimeField(null=True, blank=True)
    trrc_escalation_sent_at = models.DateTimeField(null=True, blank=True)
    trrc_escalation_recipient = models.EmailField(blank=True)
    trrc_escalation_error = models.CharField(max_length=250, blank=True)


class GmailMailbox(models.Model):
    """Single dashboard mailbox; the App Password is encrypted at rest."""
    address = models.EmailField(blank=True)
    app_password_ciphertext = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        return cls.objects.order_by('pk').first()

    @staticmethod
    def _fernet():
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
        return Fernet(key)

    def set_app_password(self, value):
        self.app_password_ciphertext = self._fernet().encrypt(value.encode()).decode() if value else ''

    def app_password(self):
        if not self.app_password_ciphertext: return ''
        return self._fernet().decrypt(self.app_password_ciphertext.encode()).decode()
