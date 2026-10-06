from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase


class ClientEditLoginTests(TestCase):
    def test_new_password_account_gets_edit_access_at_login(self):
        user = get_user_model().objects.create_user('new-member', password='test-password-only')
        self.assertFalse(user.has_perm('workorders.change_client'))
        self.assertTrue(self.client.login(username='new-member', password='test-password-only'))
        user.refresh_from_db()
        user = get_user_model().objects.get(pk=user.pk)
        self.assertTrue(user.has_perm('workorders.view_client'))
        self.assertTrue(user.has_perm('workorders.change_client'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_perm('automation_api.approve_stage2'))

    def test_login_clears_permission_cache_and_is_idempotent(self):
        user = get_user_model().objects.create_user('member')
        self.assertFalse(user.has_perm('workorders.change_client'))
        for _ in range(2):
            user_logged_in.send(sender=type(user), user=user, request=None)
        self.assertTrue(user.has_perm('workorders.change_client'))
        self.assertEqual(user.user_permissions.count(), 2)
