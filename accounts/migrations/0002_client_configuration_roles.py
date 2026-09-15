from django.db import migrations


def add_roles(apps, schema_editor):
    alias = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    for model in ('client', 'formdefinition', 'clientfilingprofile', 'workordersnapshot'):
        ct, _ = ContentType.objects.using(alias).get_or_create(app_label='workorders', model=model)
        for action in ('view', 'add', 'change'):
            if model == 'workordersnapshot' and action != 'view':
                continue
            permission, _ = Permission.objects.using(alias).get_or_create(content_type=ct, codename=f'{action}_{model}', defaults={'name': f'Can {action} {model}'})
            for role in ('Preparer', 'Approver', 'Administrator'):
                if action == 'view' or (role != 'Approver' and (model != 'formdefinition' or role == 'Administrator')):
                    group, _ = Group.objects.using(alias).get_or_create(name=role)
                    group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_dashboard_roles'), ('workorders', '0003_seed_definitions_preserve_legacy')]
    operations = [migrations.RunPython(add_roles, migrations.RunPython.noop)]
