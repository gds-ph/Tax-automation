from unittest.mock import patch
from django.test import TestCase, Client as HttpClient, override_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from .test_support import legacy_test_fixture_order, fake_data
from .models import WorkOrder
from .dashboard_actions import archive_order, archive_blocker, operational_orders, kpi_filters

@override_settings(CLIENT_FILES_URL='')
class DashboardActionsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('kpi_admin')
        self.user = get_user_model().objects.create_user('kpi_user')
        self.user.groups.add(Group.objects.get(name='Preparer'))
        self.order = legacy_test_fixture_order(actor=self.admin, data=fake_data())
        self.url = reverse('workorders:archive', args=[self.order.pk])
        self.client.force_login(self.admin)

    def test_archive_preserves_snapshot_and_audits(self):
        snapshot = self.order.current_snapshot_id
        response = self.client.post(self.url, {'expected_version':self.order.version, 'confirmed':'yes'})
        self.assertEqual(response.status_code,302)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_archived)
        self.assertEqual(self.order.current_snapshot_id,snapshot)
        self.assertTrue(self.order.audit_events.filter(changed_fields=['is_archived']).exists())
        self.assertNotContains(self.client.get(reverse('workorders:list')), self.order.work_order_id)

    def test_cancel_blocks_every_other_status(self):
        from .dashboard_actions import cancel_order
        for status in WorkOrder.Status.values:
            if status == 'AWAITING_SUBMISSION_APPROVAL':
                continue
            with self.subTest(status=status):
                self.order.status = status
                with patch('workorders.dashboard_actions._load_current', return_value=self.order):
                    with self.assertRaises(ValidationError):
                        cancel_order(actor=self.admin, work_order_id=self.order.pk,
                                     expected_version=self.order.version)
        self.order.refresh_from_db()
        url = reverse('workorders:cancel', args=[self.order.pk])
        self.assertEqual(self.client.post(url, {'expected_version': self.order.version,
                                              'confirmed': 'yes'}).status_code, 409)
        self.assertNotContains(self.client.get(reverse('workorders:detail', args=[self.order.pk])),
                               '>Cancel filing</summary>')

    def test_cancel_requires_confirmation_version_and_permission(self):
        url = reverse('workorders:cancel', args=[self.order.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        self.assertEqual(self.client.post(url, {'expected_version': 999, 'confirmed': 'yes'}).status_code, 409)
        viewer = get_user_model().objects.create_user('cancel_viewer')
        from django.contrib.auth.models import Permission
        viewer.user_permissions.add(Permission.objects.get(codename='view_workorder'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(url, {'expected_version': self.order.version, 'confirmed': 'yes'}).status_code, 403)

    def test_cancel_blocks_active_or_approved_filings(self):
        from .dashboard_actions import cancel_order
        from types import SimpleNamespace
        from .dashboard_actions import cancellation_blocker
        self.assertTrue(cancellation_blocker(SimpleNamespace(is_archived=False, stage2_approval=object())))
        self.order.status = 'PROCESSING_PREPARATION'
        with patch('workorders.dashboard_actions._load_current', return_value=self.order):
            with self.assertRaises(ValidationError):
                cancel_order(actor=self.admin, work_order_id=self.order.pk, expected_version=self.order.version)

    def test_confirmation_method_and_permission(self):
        self.assertEqual(self.client.get(self.url).status_code,405)
        self.assertEqual(self.client.post(self.url, {'expected_version':self.order.version}).status_code,400)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, {'expected_version':self.order.version,'confirmed':'yes'}).status_code,403)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_stale_version_rejected(self):
        self.assertEqual(self.client.post(self.url, {'expected_version':999,'confirmed':'yes'}).status_code,409)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)

    def test_csrf_required(self):
        client = HttpClient(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url, {'expected_version':self.order.version,'confirmed':'yes'}).status_code,403)

    def test_approved_or_running_order_blocked(self):
        from types import SimpleNamespace
        self.assertTrue(archive_blocker(SimpleNamespace(is_archived=False,stage2_approval=object())))
        self.order.status='PROCESSING_PREPARATION'
        self.assertTrue(archive_blocker(self.order))
        with patch('workorders.dashboard_actions._load_current',return_value=self.order):
            with self.assertRaises(ValidationError):
                archive_order(actor=self.admin,work_order_id=self.order.pk,expected_version=self.order.version)

    def test_kpis_exclude_configured_tests_and_archived(self):
        test = legacy_test_fixture_order(actor=self.admin,data=fake_data(client_id='TEST-639848605-00000'))
        self.assertEqual(operational_orders(WorkOrder.objects.all()).count(),1)
        archive_order(actor=self.admin,work_order_id=self.order.pk,expected_version=self.order.version)
        self.assertEqual(operational_orders(WorkOrder.objects.all()).count(),0)

    def test_links_and_scope(self):
        response=self.client.get(reverse('workorders:list'))
        self.assertEqual(len(response.context['metrics']),5)
        for metric in response.context['metrics']:
            self.assertEqual(self.client.get(reverse('workorders:list')+metric['url']).status_code,200)
        self.client.force_login(self.user)
        response=self.client.get(reverse('workorders:my-tasks'))
        self.assertEqual(response.context['page_obj'].paginator.count,0)
        self.assertTrue(all(m['count']==0 for m in response.context['metrics']))
