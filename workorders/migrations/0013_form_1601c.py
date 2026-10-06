from django.db import migrations


def seed(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    Form.objects.using(schema_editor.connection.alias).get_or_create(
        definition_key='1601cv2018_zero', defaults=dict(
            form_code='1601C', form_version='2018', expected_form_number='1601Cv2018',
            display_name='Monthly Remittance Return of Income Taxes Withheld on Compensation',
            form_selection_text='BIR Form 1601Cv2018', filing_frequency='MONTHLY',
            automation_key='PREPARE_1601CV2018_ZERO', preparation_automation_available=True,
            submission_automation_available=False))


class Migration(migrations.Migration):
    dependencies = [('workorders', '0012_registrationcardscan_preferred_sha256_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
