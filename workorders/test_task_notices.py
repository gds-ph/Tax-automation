from datetime import timedelta
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import models
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import WorkOrder, TaskNoticeRead
from .task_notices import notice
from .test_support import legacy_test_fixture_order, fake_data


class TaskNoticeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='notice-owner')
        self.other = get_user_model().objects.create_user(username='notice-other')
        for u in (self.user, self.other):
            u.groups.add(Group.objects.get(name='Preparer'))
        self.order = legacy_test_fixture_order(actor=self.user, data=fake_data())
        models.QuerySet.update(WorkOrder.objects.filter(pk=self.order.pk), status='FAILED_SYSTEM')
        self.client.force_login(self.user)

    def test_read_is_private_and_new_state_unread(self):
        url = reverse('workorders:task-notices')
        self.assertEqual(self.client.get(url).json()['count'], 1)
        self.order.refresh_from_db()
        token = notice(self.order)['token']
        open_url = reverse('workorders:open-notice', args=[self.order.pk])
        self.assertEqual(self.client.get(open_url).status_code, 405)
        self.client.post(open_url, {'token': 'stale'})
        self.assertFalse(TaskNoticeRead.objects.exists())
        self.client.post(open_url, {'token': token})
        self.assertEqual(self.client.get(url).json()['count'], 0)
        models.QuerySet.update(WorkOrder.objects.filter(pk=self.order.pk), version=self.order.version + 1)
        self.assertEqual(self.client.get(url).json()['count'], 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).json()['count'], 0)
        self.assertEqual(self.client.post(open_url, {'token': token}).status_code, 404)

    def test_completion_requires_final_package(self):
        order = SimpleNamespace(version=1, status='AWAITING_SUBMISSION_APPROVAL',
                                operational_tone='warn', stage2_approval=None)
        self.assertEqual(notice(order)['label'], 'Ready for approval')
        receipt = SimpleNamespace(finalized_at=None, final_package='')
        order.stage2_approval = SimpleNamespace(state='SUBMITTED_WAITING_FOR_CONFIRMATION', receipt_check=receipt)
        self.assertIsNone(notice(order))
        receipt.finalized_at = '2026-09-29'
        receipt.final_package = 'final.pdf'
        self.assertIn('Complete', notice(order)['label'])

    def test_unauthorized_feed_denied(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('workorders:task-notices')).status_code, 302)
        outsider = get_user_model().objects.create_user(username='notice-outsider')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse('workorders:task-notices')).status_code, 403)


class NoticeBacklogTests(TestCase):
    """Long backlogs: urgency order, a capped first view, and a safe bulk dismiss."""
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='backlog-owner')
        self.user.groups.add(Group.objects.get(name='Preparer'))
        self.client.force_login(self.user)
        self.orders = []
        for index in range(7):
            order = legacy_test_fixture_order(actor=self.user, data=fake_data(
                client_name=f'FAKE BACKLOG {index}', tin1=f'{index:03d}'))
            self.orders.append(order)
        # Six system failures and one draft that raises no notice at all.
        failed = [order.pk for order in self.orders[:6]]
        models.QuerySet.update(WorkOrder.objects.filter(pk__in=failed), status='FAILED_SYSTEM')

    def test_first_five_shown_rest_behind_show_all(self):
        html = self.client.get(reverse('workorders:task-notices')).json()['html']
        self.assertEqual(html.count('class="notice-row"'), 6)
        head, _, more = html.partition('notice-more')
        self.assertEqual(head.count('class="notice-row"'), 5)
        self.assertIn('Show all 6 notifications', html)

    def test_attention_is_listed_before_other_kinds(self):
        from .task_notices import unread
        # Make the draft a newer "Ready for approval" so recency alone would put it first.
        ready = self.orders[6]
        models.QuerySet.update(WorkOrder.objects.filter(pk=ready.pk), status='AWAITING_SUBMISSION_APPROVAL',
            preparation_status_output='AWAITING_SUBMISSION_APPROVAL', prepared_pdf='work_orders/x/p.pdf',
            prepared_pdf_sha256='a' * 64, prepared_pdf_vm_path='C:/W/p.pdf', saved_xml_path='C:/S/x.xml',
            updated_at=timezone.now() + timedelta(hours=1))
        kinds = [item['kind'] for item in unread(self.user)]
        self.assertEqual(kinds, ['attention'] * 6 + ['ready'])

    def test_read_all_clears_only_the_notices_that_were_shown(self):
        feed = reverse('workorders:task-notices')
        from .task_notices import unread
        shown = [item['token'] for item in unread(self.user)]
        # One filing changes state after the page loaded: its old token is stale.
        changed = self.orders[0]
        models.QuerySet.update(WorkOrder.objects.filter(pk=changed.pk), version=changed.version + 5)
        response = self.client.post(reverse('workorders:read-all-notices'), {'token': shown})
        self.assertRedirects(response, reverse('workorders:my-tasks'))
        remaining = self.client.get(feed).json()
        self.assertEqual(remaining['count'], 1)
        self.assertIn('FAKE BACKLOG 0', remaining['html'])

    def test_read_all_requires_post_and_csrf(self):
        url = reverse('workorders:read-all-notices')
        self.assertEqual(self.client.get(url).status_code, 405)
        from django.test import Client as BrowserClient
        strict = BrowserClient(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(url, {'token': ['x']}).status_code, 403)
        self.assertFalse(TaskNoticeRead.objects.exists())
