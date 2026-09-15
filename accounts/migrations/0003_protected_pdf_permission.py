from django.db import migrations


def grant_pdf_access(apps,schema_editor):
    alias=schema_editor.connection.alias
    CT=apps.get_model('contenttypes','ContentType')
    Permission=apps.get_model('auth','Permission')
    Group=apps.get_model('auth','Group')
    ct,_=CT.objects.using(alias).get_or_create(app_label='workorders',model='workorder')
    permission,_=Permission.objects.using(alias).get_or_create(content_type=ct,codename='view_prepared_pdf',defaults={'name':'Can download protected prepared PDF'})
    for group in Group.objects.using(alias).filter(name__in=['Preparer','Approver','Administrator']):
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies=[('accounts','0002_client_configuration_roles'),('workorders','0006_alter_workorder_options')]
    operations=[migrations.RunPython(grant_pdf_access,migrations.RunPython.noop)]
