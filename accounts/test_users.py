from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import FeishuIdentity


class RegisteredUsersTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('users_admin', password='test-only')
        self.member = get_user_model().objects.create_user('employee', first_name='Example Employee')
        FeishuIdentity.objects.create(user=self.member, app_id='app', tenant_key='tenant', open_id='private-open-id')
        self.url = reverse('registered-users')

    def test_admin_can_view_and_search_without_exposing_identity_keys(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertContains(response, 'Example Employee')
        self.assertContains(response, 'Feishu')
        self.assertContains(response, 'Never signed in')
        self.assertNotContains(response, 'private-open-id')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotContains(self.client.get(self.url, {'q': 'missing-user'}), 'Example Employee')

    def test_non_admin_and_anonymous_cannot_view(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.member.is_staff = True
        self.member.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
