import hashlib
import secrets
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from workorders.validators import sha256_hex


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


class Stage2Approval(ServiceModel):
    """Approval for reopening/revalidation only; never authorizes live submission."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.OneToOneField('workorders.WorkOrder', on_delete=models.PROTECT, related_name='stage2_approval')
    snapshot = models.ForeignKey('workorders.WorkOrderSnapshot', on_delete=models.PROTECT)
    approved_by = models.ForeignKey('auth.User', on_delete=models.PROTECT)
    approved_at = models.DateTimeField(default=timezone.now)
    pdf_sha256 = models.CharField(max_length=64, validators=[sha256_hex])
    comment = models.TextField(blank=True)
    state = models.CharField(max_length=40, default='QUEUED')
    attempt = models.OneToOneField(PreparationAttempt, null=True, blank=True, on_delete=models.PROTECT, related_name='stage2_approval')

    class Meta:
        permissions = [('approve_stage2', 'Can approve Stage 2 revalidation')]
