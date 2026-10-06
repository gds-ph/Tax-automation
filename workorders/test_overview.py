from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import models as django_models
from django.test import Client as BrowserClient, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import WorkOrder
from .test_support import legacy_test_fixture_order as create_work_order, fake_data


@override_settings(CLIENT_FILES_URL='')
class OverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.preparer = get_user_model().objects.create_user(username='overview_preparer')
        cls.preparer.groups.add(Group.objects.get(name='Preparer'))
        cls.outsider = get_user_model().objects.create_user(username='overview_outsider')
        cls.recent = create_work_order(actor=cls.preparer, data=fake_data(client_name='FAKE RECENT CLIENT'))
        cls.old = create_work_order(actor=cls.preparer, data=fake_data(client_name='FAKE OLD CLIENT'))
        # created_at is not editable, so age the second filing through the
        # same escape hatch the services layer uses for versioned writes.
        django_models.QuerySet.update(WorkOrder.objects.filter(pk=cls.old.pk),
                                      created_at=timezone.now() - timedelta(days=200))

    def setUp(self):
        self.client.force_login(self.preparer)
        self.url = reverse('workorders:overview')

    def test_default_range_covers_recent_filings_only(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'FAKE RECENT CLIENT')
        self.assertNotContains(response, 'FAKE OLD CLIENT')
        self.assertEqual(response.context['totals']['filings'], 1)

    def test_explicit_range_and_form_filter(self):
        wide = self.client.get(self.url, {'start': '2020-01-01', 'end': timezone.localdate().isoformat()})
        self.assertContains(wide, 'FAKE OLD CLIENT')
        self.assertEqual(wide.context['totals']['filings'], 2)
        other = self.client.get(self.url, {'form': '1601C'})
        self.assertEqual(other.context['totals']['filings'], 0)
        self.assertEqual(other.context['form_code'], '1601C')

    def test_invalid_range_falls_back_without_error(self):
        response = self.client.get(self.url, {'start': 'not-a-date', 'end': '2026-13-45', 'form': '../etc'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['preset'], '30d')
        self.assertEqual(response.context['form_code'], '')

    def test_csv_export_is_attached_and_escapes_formulas(self):
        django_models.QuerySet.update(WorkOrder.objects.filter(pk=self.recent.pk), client_name='=cmd|calc')
        response = self.client.get(self.url, {'export': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        body = response.content.decode('utf-8')
        self.assertIn("'=cmd|calc", body)
        self.assertNotIn(',=cmd|calc', body)

    def test_requires_work_order_permission(self):
        browser = BrowserClient()
        browser.force_login(self.outsider)
        self.assertEqual(browser.get(self.url).status_code, 403)
        self.assertEqual(browser.get(self.url, {'export': 'csv'}).status_code, 403)
        anonymous = BrowserClient()
        self.assertEqual(anonymous.get(self.url).status_code, 302)
