from django.db import migrations


def grant(apps, schema_editor):
    ct, _ = apps.get_model('contenttypes', 'ContentType').objects.get_or_create(app_label='automation_api', model='stage2approval')
    permission, _ = apps.get_model('auth', 'Permission').objects.get_or_create(content_type=ct, codename='approve_stage2', defaults={'name': 'Can approve Stage 2 revalidation'})
    for group in apps.get_model('auth', 'Group').objects.filter(name__in=['Approver', 'Administrator']):
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [('automation_api', '0004_stage2approval'), ('accounts', '0003_protected_pdf_permission')]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
