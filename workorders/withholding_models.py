import uuid
from django.conf import settings
from django.db import models


class ExpandedWithholdingDraft(models.Model):
    """One original monthly draft; revisions retain reviewed inputs."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey('Client', on_delete=models.PROTECT, related_name='expanded_withholding_drafts')
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    rows = models.JSONField(default=list)
    total = models.DecimalField(max_digits=18, decimal_places=2)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['client', 'year', 'month'], name='unique_0619e_draft_period'),
                       models.CheckConstraint(condition=models.Q(month__in=[1, 2, 4, 5, 7, 8, 10, 11]), name='valid_0619e_month')]


class ExpandedWithholdingRevision(models.Model):
    draft = models.ForeignKey(ExpandedWithholdingDraft, on_delete=models.PROTECT, related_name='revisions')
    version = models.PositiveIntegerField()
    rows = models.JSONField()
    total = models.DecimalField(max_digits=18, decimal_places=2)
    client_snapshot = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['draft', 'version'], name='unique_0619e_revision')]
