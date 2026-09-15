from django.db import migrations


def seed(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    catalog = [
        ('1701', 'Annual Income Tax Return — Individual', 'ANNUAL'),
        ('1701A', 'Annual Income Tax Return — Individual (1701A)', 'ANNUAL'),
        ('2550Q', 'Quarterly Value-Added Tax Return', 'QUARTERLY'),
        ('0619E', 'Monthly Remittance of Expanded Withholding Tax', 'MONTHLY'),
        ('1601EQ', 'Quarterly Expanded Withholding Tax Return', 'QUARTERLY'),
        ('1604E', 'Annual Information Return — Expanded Withholding Tax', 'ANNUAL'),
    ]
    for code, name, frequency in catalog:
        Form.objects.using(schema_editor.connection.alias).get_or_create(
            form_code=code, form_version='', defaults={
                'definition_key': 'cor_' + code.lower(), 'display_name': name,
                'filing_frequency': frequency, 'preparation_automation_available': False,
                'submission_automation_available': False, 'automation_key': '', 'is_active': True})


class Migration(migrations.Migration):
    dependencies = [('workorders', '0008_registrationsetup')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
