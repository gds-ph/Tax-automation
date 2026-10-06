import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SystemSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.CharField(max_length=200)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']


class SystemLog(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event = models.CharField(max_length=60, db_index=True)
    level = models.CharField(max_length=10, default='INFO', db_index=True)
    route = models.CharField(max_length=120, blank=True)
    status = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    counts = models.JSONField(default=dict)

    class Meta:
        ordering = ['-created_at', '-pk']


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Audit events are append-only.")

    def delete(self):
        raise ValidationError("Audit events are append-only.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Create validated audit events individually.")


class AuditEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "CREATED", "Created"
        EDITED = "EDITED", "Edited"
        STATUS_CHANGED = "STATUS_CHANGED", "Status changed"
        PREPARATION_RESULT = "PREPARATION_RESULT", "Preparation result"
        APPROVED = "APPROVED", "Approved (reserved)"
        REJECTED = "REJECTED", "Rejected (reserved)"
        API_LEASE = "API_LEASE", "Preparation lease"
        AGENT_CREATED = "AGENT_CREATED", "Agent created"
        AGENT_TOKEN_ROTATED = "AGENT_TOKEN_ROTATED", "Agent token rotated"
        AGENT_DISABLED = "AGENT_DISABLED", "Agent disabled"
        PDF_UPLOADED = "PDF_UPLOADED", "Prepared PDF uploaded"
        LEASE_RENEWED = "LEASE_RENEWED", "Preparation lease renewed"
        ATTEMPT_ABANDONED = "ATTEMPT_ABANDONED", "Preparation stopped by operator"
        CONFIG_CREATED = "CONFIG_CREATED", "Configuration created"
        CONFIG_EDITED = "CONFIG_EDITED", "Configuration edited"
        SNAPSHOT_REFRESHED = "SNAPSHOT_REFRESHED", "Snapshot refreshed"
        LEGACY_LINKED = "LEGACY_LINKED", "Historical work order linked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey("workorders.WorkOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    agent = models.ForeignKey("automation_api.Agent", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    client = models.ForeignKey("workorders.Client", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    form_definition = models.ForeignKey("workorders.FormDefinition", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    client_filing_profile = models.ForeignKey("workorders.ClientFilingProfile", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    snapshot = models.ForeignKey("workorders.WorkOrderSnapshot", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="ebir_audit_events")
    performed_by_agent = models.ForeignKey("automation_api.Agent", on_delete=models.PROTECT, null=True, blank=True, related_name="performed_events")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    old_status = models.CharField(max_length=40, blank=True)
    new_status = models.CharField(max_length=40, blank=True)
    changed_fields = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=(models.Q(actor__isnull=False, performed_by_agent__isnull=True)
                | models.Q(actor__isnull=True, performed_by_agent__isnull=False)), name="audit_exactly_one_actor"),
            models.CheckConstraint(condition=(
                models.Q(work_order__isnull=False, agent__isnull=True, client__isnull=True, form_definition__isnull=True, client_filing_profile__isnull=True)
                | models.Q(work_order__isnull=True, agent__isnull=False, client__isnull=True, form_definition__isnull=True, client_filing_profile__isnull=True)
                | models.Q(work_order__isnull=True, agent__isnull=True, client__isnull=False, form_definition__isnull=True, client_filing_profile__isnull=True)
                | models.Q(work_order__isnull=True, agent__isnull=True, client__isnull=True, form_definition__isnull=False, client_filing_profile__isnull=True)
                | models.Q(work_order__isnull=True, agent__isnull=True, client__isnull=True, form_definition__isnull=True, client_filing_profile__isnull=False)
            ), name="audit_exactly_one_subject"),
        ]

    def clean(self):
        super().clean()
        if bool(self.actor_id) == bool(self.performed_by_agent_id):
            raise ValidationError("An event requires exactly one human or worker actor.")
        if sum(bool(value) for value in (self.work_order_id, self.agent_id, self.client_id, self.form_definition_id, self.client_filing_profile_id)) != 1:
            raise ValidationError("An audit event requires exactly one subject.")
        if self.snapshot_id and self.snapshot.work_order_id != self.work_order_id:
            raise ValidationError("Audit snapshot must belong to its work order.")
        if not isinstance(self.changed_fields, list) or any(
            not isinstance(name, str) or not name.isidentifier() for name in self.changed_fields
        ):
            raise ValidationError({"changed_fields": "Record field names only, never values or secrets."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audit events are append-only.")
        self.full_clean()
        # Prevent a newly constructed instance with an existing UUID overwriting a row.
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only.")

    def __str__(self):
        return f"{self.kind} ({self.id})"
