"""Seed definitions and preserve pre-refactor rows without inferring client identity."""
import hashlib
import json
from django.db import migrations


def forwards(apps, schema_editor):
    alias = schema_editor.connection.alias
    Form = apps.get_model('workorders', 'FormDefinition')
    Form.objects.using(alias).get_or_create(definition_key='2551qv2018_zero', defaults=dict(
        form_code='2551Q', form_version='2018', expected_form_number='2551Qv2018',
        display_name='Quarterly Percentage Tax Return', form_selection_text='BIR Form 2551Qv2018',
        filing_frequency='QUARTERLY', automation_key='PREPARE_2551QV2018_ZERO',
        preparation_automation_available=True, submission_automation_available=False))
    Form.objects.using(alias).get_or_create(definition_key='planned_1701q', defaults=dict(
        form_code='1701Q', form_version='', expected_form_number='', display_name='Quarterly Income Tax Return',
        form_selection_text='', filing_frequency='QUARTERLY', automation_key='',
        preparation_automation_available=False, submission_automation_available=False))
    Order = apps.get_model('workorders', 'WorkOrder')
    Snapshot = apps.get_model('workorders', 'WorkOrderSnapshot')
    for order in Order.objects.using(alias).filter(current_snapshot__isnull=True).iterator():
        # Capture every old scalar column, including original audit/result metadata.
        original = {}
        for field in Order._meta.concrete_fields:
            value = getattr(order, field.attname)
            if value is not None and not isinstance(value, (str, int, float, bool, dict, list)):
                value = str(value)
            original[field.attname] = value
        data = dict(schema_version=1, origin='legacy_m2_import', legacy_columns=original,
                    form=dict(definition_key='', filing_frequency='QUARTERLY', form_code=order.form_code,
                              expected_form_number=order.expected_form_number))
        digest = hashlib.sha256(json.dumps(dict(data=data, source_versions={}), sort_keys=True,
                    separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest()
        snap = Snapshot.objects.using(alias).create(work_order_id=order.pk, revision=1, data=data,
                    source_versions={}, sha256=digest, created_by=None)
        Order.objects.using(alias).filter(pk=order.pk).update(current_snapshot_id=snap.pk)


class Migration(migrations.Migration):
    dependencies = [('workorders', '0002_client_clientfilingprofile_formdefinition_and_more')]
    # Intentionally irreversible: restoring the verified local backup is safer than
    # dropping new client/snapshot records or discarding their historical links.
    operations = [migrations.RunPython(forwards)]
