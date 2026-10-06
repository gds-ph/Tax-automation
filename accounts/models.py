from django.db import models
from django.conf import settings

class FeishuIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    app_id = models.CharField(max_length=100)
    tenant_key = models.CharField(max_length=100)
    open_id = models.CharField(max_length=150)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['app_id', 'tenant_key', 'open_id'], name='unique_feishu_identity')]
