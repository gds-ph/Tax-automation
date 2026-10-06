from unittest.mock import patch
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.utils import timezone
from django.core.management import call_command
from .models import SystemLog
from .operational import record

class LogTests(TestCase):
    def test_admin_only(self):
        self.assertEqual(self.client.get('/logs/').status_code,302)
        user=get_user_model().objects.create_user('reader',password='password')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/logs/').status_code,200)
        user.is_superuser=True;user.save()
        self.assertEqual(self.client.get('/logs/').status_code,200)
        self.assertEqual(self.client.get('/logs/?tab=activity').status_code,200)

    def test_secrets_not_logged(self):
        self.client.post('/login/?code=secret-code',{'username':'private-name','password':'secret-password'})
        rows=str(list(SystemLog.objects.values()))
        for value in ['private-name','secret-password','secret-code']:
            self.assertNotIn(value,rows)
        self.assertTrue(SystemLog.objects.filter(event='login_failed').exists())

    def test_logging_failure_does_not_break_login(self):
        with patch('audit.operational.SystemLog.objects.create',side_effect=OperationalError('secret')):
            response=self.client.post('/login/',{'username':'bad','password':'secret'})
        self.assertEqual(response.status_code,200)

    @patch('automation_api.management.commands.check_bir_receipts.poll_receipts',return_value=(2,1,0))
    def test_retention_and_background_summary(self,poll):
        old=SystemLog.objects.create(event='receipt_check',created_at=timezone.now()-timedelta(days=31))
        call_command('check_bir_receipts')
        self.assertFalse(SystemLog.objects.filter(pk=old.pk).exists())
        self.assertEqual(SystemLog.objects.get().counts,{'checked':2,'received':1,'errors':0})
