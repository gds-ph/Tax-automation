from django.db import migrations
from django.db.models import F

def seed(apps, schema_editor):
    forms=apps.get_model('workorders','FormDefinition').objects.using(schema_editor.connection.alias)
    values=dict(definition_key='0619e_zero', form_code='0619E', form_version='2018', expected_form_number='0619E', display_name='Monthly Remittance of Expanded Withholding Tax', form_selection_text='BIR Form 0619E', filing_frequency='MONTHLY', automation_key='PREPARE_0619E_ZERO', preparation_automation_available=False, submission_automation_available=False)
    existing=forms.filter(definition_key='cor_0619e')
    if existing.exists():
        existing.update(**values, version=F('version')+1)
    else:
        forms.get_or_create(definition_key='0619e_zero', defaults=values)

class Migration(migrations.Migration):
    dependencies=[('workorders','0025_expanded_withholding_drafts')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
