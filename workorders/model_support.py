from django.core.exceptions import ValidationError
from django.db import models


class GuardedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use the audited service layer for changes.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use the audited service layer for creation.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use the audited service layer for changes.")

    def delete(self):
        raise ValidationError("Deletion is disabled to preserve filing history.")


class ServiceModel(models.Model):
    objects = GuardedQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, _service_write=False, **kwargs):
        if not _service_write:
            raise ValidationError("Use the audited service layer to save this record.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Deletion is disabled to preserve filing history.")
