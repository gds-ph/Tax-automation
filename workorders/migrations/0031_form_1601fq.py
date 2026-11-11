from django.db import migrations


def seed(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    Form.objects.using(schema_editor.connection.alias).get_or_create(
        definition_key='1601fq_zero', defaults=dict(
            form_code='1601FQ', form_version='2018', expected_form_number='1601FQ',
            display_name='Quarterly Remittance Return of Final Income Taxes Withheld',
            form_selection_text='BIR Form 1601FQ', filing_frequency='QUARTERLY',
            automation_key='PREPARE_1601FQ_ZERO', preparation_automation_available=False,
            submission_automation_available=False))


class Migration(migrations.Migration):
    dependencies = [('workorders', '0030_quarterly_pad_confirmation')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
