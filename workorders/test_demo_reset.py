from django.contrib.auth import get_user_model
from django.test import TestCase, Client as BrowserClient
from django.urls import reverse
from .test_support import make_profile, order_data
from .services import create_work_order, transition_work_order
from .models import WorkOrder


class DemoResetTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username='reset_admin', password='fake-only')
        self.profile = make_profile(self.actor, client_data={'client_code': 'DUMMY-CLIENT-001',
            'registered_name': 'ABC TEST COMPANY', 'tin1': '650', 'tin2': '703', 'tin3': '312', 'tin4': '00000'})
        self.order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=order_data(zero_filing_approved=True))
        self.order = transition_work_order(actor=self.actor, work_order_id=self.order.pk,
            expected_version=self.order.version, target='READY_TO_PREPARE')
        self.url = reverse('workorders:reset-demo', args=[self.profile.client_id])
        self.client.force_login(self.actor)

    def data(self):
        response = self.client.get(self.url)
        return {'token': response.context['form']['token'].value(),
            'confirmed_stopped': 'on', 'confirmed_scope': 'on'}

    def test_get_is_read_only_and_post_downloads_scoped_script(self):
        other_year = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=order_data(filing_year='2025'))
        data = self.data()
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        text = response.content.decode()
        self.assertIn(str(self.order.pk), text)
        self.assertNotIn(str(other_year.pk), text)
        self.assertIn('already completed', text)
        self.assertNotIn('Token', text)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_archived)
        other_year.refresh_from_db()
        self.assertFalse(other_year.is_archived)
        self.assertEqual(WorkOrder.objects.count(), 2)

    def test_confirmation_required(self):
        data = self.data()
        del data['confirmed_stopped']
        self.client.post(self.url, data)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_confirmed_reset_releases_running_attempt(self):
        from uuid import uuid4
        from automation_api.services import create_agent
        from automation_api.worker_services import claim
        agent, _ = create_agent(actor=self.actor, name='FAKE-RESET-WORKER')
        attempt = claim(agent=agent, request_id=uuid4(), automation_keys=['PREPARE_2551QV2018_ZERO'])
        response = self.client.post(self.url, self.data())
        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(attempt.state, 'ABANDONED')
        self.assertIsNone(attempt.execution_slot)
        self.assertTrue(self.order.is_archived)

    def test_stale_confirmation_cannot_reset_new_job(self):
        data = self.data()
        create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk, data=order_data(filing_quarter=4))
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_csrf_and_authentication_required(self):
        browser = BrowserClient(enforce_csrf_checks=True)
        self.assertEqual(browser.get(self.url).status_code, 302)
        browser.force_login(self.actor)
        self.assertEqual(browser.post(self.url, self.data()).status_code, 403)

    def test_other_client_not_supported(self):
        other = make_profile(self.actor)
        self.assertEqual(self.client.get(reverse('workorders:reset-demo', args=[other.client_id])).status_code, 404)

    def test_non_superuser_denied(self):
        from django.contrib.auth.models import Permission
        user = get_user_model().objects.create_user(username='operator', password='fake-only')
        user.user_permissions.add(*Permission.objects.filter(codename__in=['change_workorder', 'change_agent']))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
