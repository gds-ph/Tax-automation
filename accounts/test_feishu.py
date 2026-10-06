import time
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from .models import FeishuIdentity


@override_settings(FEISHU_APP_ID='test-app', FEISHU_APP_SECRET='test-secret',
                   FEISHU_TENANT_KEY='office', FEISHU_REDIRECT_URI='https://example.test/auth/feishu/callback/')
class FeishuTests(TestCase):
    def begin(self):
        response = self.client.post(reverse('feishu-login'))
        self.assertEqual(response.status_code, 302)
        params = parse_qs(urlsplit(response.url).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertNotIn('client_secret', params)
        return params['state'][0]

    def finish(self, state):
        return self.client.get(reverse('feishu-callback'), {'code': 'test-code', 'state': state})

    @patch('accounts.feishu.api')
    def test_employee_permissions_and_replay_rejected(self, api):
        api.side_effect = [{'access_token': 'token'}, {'data': {'tenant_key': 'office', 'open_id': 'employee', 'name': 'Employee'}}]
        state = self.begin()
        self.assertEqual(self.finish(state).status_code, 302)
        user = FeishuIdentity.objects.get().user
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.has_perm('workorders.view_client'))
        self.assertTrue(user.has_perm('workorders.change_client'))
        self.assertTrue(user.has_perm('workorders.add_workorder'))
        self.assertTrue(user.has_perm('workorders.change_workorder'))
        self.assertTrue(user.has_perm('automation_api.approve_stage2'))
        self.assertEqual(self.client.post(reverse('workorders:gmail-status'), {}).status_code, 403)
        self.finish(state)
        self.assertEqual(api.call_count, 2)

    @patch('accounts.feishu.api')
    def test_other_organization_rejected(self, api):
        api.side_effect = [{'access_token': 'token'}, {'data': {'tenant_key': 'outsider', 'open_id': 'employee'}}]
        self.finish(self.begin())
        self.assertFalse(FeishuIdentity.objects.exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    @patch('accounts.feishu.api')
    def test_state_and_expiration_checked_before_exchange(self, api):
        self.begin()
        self.finish('wrong')
        self.assertFalse(api.called)
        state = self.begin()
        session = self.client.session
        pending = session['feishu_login']; pending['created'] = time.time()-601
        session['feishu_login'] = pending; session.save()
        self.finish(state)
        self.assertFalse(api.called)

    @patch('accounts.feishu.api')
    def test_email_does_not_link_to_local_admin(self, api):
        admin = get_user_model().objects.create_superuser('admin', 'same@example.test', 'test-password')
        api.side_effect = [{'access_token': 'token'}, {'data': {'tenant_key': 'office', 'open_id': 'employee', 'email': admin.email}}]
        self.finish(self.begin())
        self.assertNotEqual(FeishuIdentity.objects.get().user_id, admin.pk)

    @patch('accounts.feishu.api')
    def test_disabled_user_stays_disabled(self, api):
        user=get_user_model().objects.create_user('disabled', is_active=False)
        FeishuIdentity.objects.create(user=user, app_id='test-app', tenant_key='office', open_id='employee')
        api.side_effect = [{'access_token': 'token'}, {'data': {'tenant_key': 'office', 'open_id': 'employee'}}]
        self.finish(self.begin())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_start_requires_csrf(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('feishu-login')).status_code,403)
        self.assertEqual(self.client.get(reverse('feishu-login')).status_code,405)

    @override_settings(FEISHU_TENANT_KEY='')
    @patch('accounts.feishu.api')
    def test_missing_configuration_fails_closed(self, api):
        self.assertNotContains(self.client.get(reverse('login')), 'Sign in with Feishu')
        self.client.post(reverse('feishu-login'))
        self.assertNotIn('feishu_login',self.client.session)
        self.assertFalse(api.called)
