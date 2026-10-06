from django.db import migrations


def seed(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    Form.objects.using(schema_editor.connection.alias).get_or_create(
        definition_key='0619f_zero', defaults=dict(
            form_code='0619F', form_version='2018', expected_form_number='0619F',
            display_name='Monthly Remittance Form of Final Income Taxes Withheld',
            form_selection_text='BIR Form 0619F', filing_frequency='MONTHLY',
            automation_key='PREPARE_0619F_ZERO', preparation_automation_available=False,
            submission_automation_available=False))


class Migration(migrations.Migration):
    dependencies = [('workorders', '0019_alter_client_rdo_email')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
