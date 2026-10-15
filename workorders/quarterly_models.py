import uuid
from django.conf import settings
from django.db import models


class QuarterlyWithholdingDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey('Client', on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField()
    quarter = models.PositiveSmallIntegerField()
    data = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['client', 'year', 'quarter'], name='unique_1601eq_draft_period'),
                       models.CheckConstraint(condition=models.Q(quarter__range=(1, 4)), name='valid_1601eq_draft_quarter')]


class QuarterlyWithholdingRevision(models.Model):
    draft = models.ForeignKey(QuarterlyWithholdingDraft, on_delete=models.PROTECT, related_name='revisions')
    version = models.PositiveIntegerField()
    data = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['draft', 'version'], name='unique_1601eq_draft_revision')]
