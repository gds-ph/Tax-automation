from django.db import migrations


def seed(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    Form.objects.using(schema_editor.connection.alias).get_or_create(
        definition_key='1600vt_zero', defaults=dict(
            form_code='1600VT', form_version='2018', expected_form_number='1600VTv2018',
            display_name='Monthly Remittance Return of Value-Added Tax Withheld',
            form_selection_text='BIR Form 1600VTv2018', filing_frequency='MONTHLY',
            automation_key='PREPARE_1600VT_ZERO', preparation_automation_available=False,
            submission_automation_available=False))


class Migration(migrations.Migration):
    dependencies = [('workorders', '0020_form_0619f')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
