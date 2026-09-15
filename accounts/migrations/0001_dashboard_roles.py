from django.db import migrations


def create_dashboard_roles(apps, schema_editor):
    """Create permissions explicitly because post_migrate has not run yet."""
    alias = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    specs = {
        "workorders.view_workorder": ("workorders", "workorder", "Can view work order"),
        "workorders.add_workorder": ("workorders", "workorder", "Can add work order"),
        "workorders.change_workorder": ("workorders", "workorder", "Can change work order"),
        "audit.view_auditevent": ("audit", "auditevent", "Can view audit event"),
        "automation_api.view_agent": ("automation_api", "agent", "Can view agent"),
    }
    permissions = {}
    for key, (app_label, model, name) in specs.items():
        content_type, _ = ContentType.objects.using(alias).get_or_create(app_label=app_label, model=model)
        permissions[key], _ = Permission.objects.using(alias).get_or_create(
            content_type=content_type, codename=key.split(".")[1], defaults={"name": name}
        )
    reader = ["workorders.view_workorder", "audit.view_auditevent"]
    writer = reader + ["workorders.add_workorder", "workorders.change_workorder"]
    for name, keys in {
        "Preparer": writer,
        "Approver": reader,
        "Administrator": writer + ["automation_api.view_agent"],
    }.items():
        group, _ = Group.objects.using(alias).get_or_create(name=name)
        group.permissions.set([permissions[key] for key in keys])


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("workorders", "0001_initial"),
        ("audit", "0001_initial"),
        ("automation_api", "0001_initial"),
    ]
    # Reversal preserves existing users' group assignments and permissions.
    operations = [migrations.RunPython(create_dashboard_roles, migrations.RunPython.noop)]
