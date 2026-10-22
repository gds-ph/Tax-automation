from django.test import Client, TestCase
from django.urls import reverse
from automation_api.test_worker_api import WorkerApiTests
from automation_api.models import CancellationCleanup
from .models import WorkOrder


class AdminRemovalTests(TestCase):
    setUpTestData = classmethod(WorkerApiTests.setUpTestData.__func__)
    setUp = WorkerApiTests.setUp
    make_order = WorkerApiTests.make_order
    claim = WorkerApiTests.claim
    job = WorkerApiTests.job
    upload = WorkerApiTests.upload
    result = WorkerApiTests.result

    def prepare_selection(self):
        job = self.job()
        self.upload(job)
        self.result(job)
        self.order = WorkOrder.objects.get()
        self.browser = Client()
        self.browser.force_login(self.actor)
        self.url = reverse('workorders:remove', args=[self.order.pk])
        self.data = {'confirmed': 'yes', 'expected_version': self.order.version}

    def test_dashboard_popup_and_cleanup(self):
        self.prepare_selection()
        page = self.browser.get(reverse('workorders:list'))
        self.assertContains(page, 'Delete this work order?')
        self.assertNotContains(page, 'Manage / delete work orders')
        self.assertFalse(CancellationCleanup.objects.exists())
        response = self.browser.post(self.url, self.data)
        self.assertRedirects(response, reverse('workorders:list'))
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_archived)
        self.assertEqual(CancellationCleanup.objects.get().state, 'PENDING')

    def test_missing_confirmation_and_stale_version(self):
        self.prepare_selection()
        for data in ({'expected_version': self.order.version}, {'confirmed':'yes','expected_version':999}):
            self.browser.post(self.url, data)
            self.order.refresh_from_db()
            self.assertFalse(self.order.is_archived)
            self.assertFalse(CancellationCleanup.objects.exists())
        self.assertEqual(self.browser.get(self.url).status_code, 405)

    def test_non_admin_denied(self):
        self.prepare_selection()
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        user=get_user_model().objects.create_user('ordinary')
        user.user_permissions.add(*Permission.objects.filter(codename__in=['view_workorder','change_workorder']))
        self.browser.force_login(user)
        self.assertNotContains(self.browser.get(reverse('workorders:list')), 'Delete this work order?')
        self.assertEqual(self.browser.post(self.url,self.data).status_code,403)
        self.assertFalse(CancellationCleanup.objects.exists())
