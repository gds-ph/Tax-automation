from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .assignments import assign
from .test_support import legacy_test_fixture_order, fake_data


class AssignmentTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='assigner')
        self.member = get_user_model().objects.create_user(username='member', first_name='Team Member')
        for user in (self.actor, self.member):
            user.groups.add(Group.objects.get(name='Preparer'))
        self.order = legacy_test_fixture_order(actor=self.actor, data=fake_data(client_name='ASSIGNMENT CLIENT'))
        self.client.force_login(self.actor)

    def test_assignment_filters_and_preserves_filing_revision(self):
        version, status = self.order.version, self.order.status
        response = self.client.post(reverse('workorders:assign', args=[self.order.pk]),
                                    {'assigned_to': self.member.pk, 'assignment_version': 0})
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual((self.order.version, self.order.status), (version, status))
        self.assertEqual(self.order.assigned_to, self.member)
        self.assertEqual(self.order.audit_events.filter(changed_fields=['assigned_to']).count(), 1)
        self.assertContains(self.client.get(reverse('workorders:my-tasks')), 'ASSIGNMENT CLIENT')
        self.assertContains(self.client.get(reverse('workorders:list')), 'ASSIGNMENT CLIENT')
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse('workorders:my-tasks')), 'ASSIGNMENT CLIENT')
        self.assertNotContains(self.client.get(reverse('workorders:detail', args=[self.order.pk])), 'Save assignment')

    def test_stale_assignment_rejected_and_unassign_supported(self):
        assign(actor=self.actor, pk=self.order.pk, assigned_to=self.member, assignment_version=0)
        url = reverse('workorders:assign', args=[self.order.pk])
        self.assertEqual(self.client.post(url, {'assigned_to': '', 'assignment_version': 0}).status_code, 409)
        self.assertEqual(self.client.post(url, {'assigned_to': '', 'assignment_version': 1}).status_code, 302)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.assigned_to)

    def test_outsider_and_inactive_assignee_rejected(self):
        outsider = get_user_model().objects.create_user(username='outsider')
        url = reverse('workorders:assign', args=[self.order.pk])
        self.assertEqual(self.client.post(url, {'assigned_to': outsider.pk, 'assignment_version': 0}).status_code, 400)
        self.member.is_active = False
        self.member.save()
        self.assertEqual(self.client.post(url, {'assigned_to': self.member.pk, 'assignment_version': 0}).status_code, 400)
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(url, {'assigned_to': '', 'assignment_version': 0}).status_code, 403)
        self.assertEqual(self.client.get(reverse('workorders:my-tasks')).status_code, 403)
