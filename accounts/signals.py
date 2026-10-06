"""Client-detail access shared by all signed-in office users."""
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in, dispatch_uid='accounts.client_edit_on_login')
def allow_client_edit_on_login(sender, user, **kwargs):
    if not user.is_active:
        return
    user.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='workorders',
        codename__in=['view_client', 'change_client']))
    for name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
        user.__dict__.pop(name, None)
