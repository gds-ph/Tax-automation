from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import SystemSetting

class OperationsSettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='settings-admin', is_superuser=True)
        self.client.force_login(self.user)
        self.url = reverse('operation-settings')

    def test_save_both_timings(self):
        response = self.client.post(self.url, {'rdo_email': 'rdo@example.com', 'receipt_minutes': '2', 'trrc_minutes': '5'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SystemSetting.objects.get(key='trrc_escalation_recipient').value, 'rdo@example.com')
        self.assertEqual(SystemSetting.objects.get(key='receipt_check_interval_minutes').value, '2')
        self.assertEqual(SystemSetting.objects.get(key='trrc_escalation_after_minutes').value, '5')

    def test_invalid_interval_saves_neither_setting(self):
        for value in ['0', '-1', '1441', 'text']:
            self.client.post(self.url, {'rdo_email': 'rdo@example.com', 'receipt_minutes': value, 'trrc_minutes': '5'})
        self.assertFalse(SystemSetting.objects.exists())

    def test_regular_user_cannot_read_or_save_settings(self):
        self.user.is_superuser = False
        self.user.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'rdo_email': 'rdo@example.com', 'receipt_minutes': '2', 'trrc_minutes': '5'}).status_code, 403)
        self.assertFalse(SystemSetting.objects.exists())

    def test_invalid_email_saves_nothing(self):
        self.client.post(self.url, {'rdo_email': 'bad', 'receipt_minutes': '1', 'trrc_minutes': '0'})
        self.assertFalse(SystemSetting.objects.exists())
