from django.db import migrations
from django.db.models import F


def seed(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    forms = Form.objects.using(schema_editor.connection.alias)
    values = dict(definition_key='2550qv2024_zero', form_code='2550Q', form_version='2024',
        expected_form_number='2550Qv2024', display_name='Quarterly Value-Added Tax Return',
        form_selection_text='BIR Form 2550Qv2024 - Quarterly Value-Added (VAT) Tax Return',
        filing_frequency='QUARTERLY', automation_key='PREPARE_2550QV2024_ZERO',
        preparation_automation_available=True, submission_automation_available=False)
    # Upgrade in place so existing client cards retain their identity and settings.
    existing = forms.filter(definition_key='cor_2550q')
    if existing.exists():
        existing.update(**values, version=F('version') + 1)
    else:
        forms.get_or_create(definition_key='2550qv2024_zero', defaults=values)


class Migration(migrations.Migration):
    dependencies = [('workorders', '0023_cancelled_constraint')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
