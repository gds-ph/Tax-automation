from django.db import migrations
from django.db.models import F

def enable_preparation(apps, schema_editor):
    Form = apps.get_model('workorders', 'FormDefinition')
    Form.objects.using(schema_editor.connection.alias).filter(definition_key='cor_1601eq').update(
        form_version='2018', expected_form_number='1601EQ', form_selection_text='BIR Form 1601EQ',
        automation_key='PREPARE_1601EQ_ZERO', preparation_automation_available=True,
        submission_automation_available=False, version=F('version') + 1)

class Migration(migrations.Migration):
    dependencies = [('workorders', '0014_savedcompany')]
    operations = [migrations.RunPython(enable_preparation, migrations.RunPython.noop)]
