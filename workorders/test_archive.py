from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from .archive_services import archive_stopped_order
from .services import create_work_order, transition_work_order, validate_readiness, edit_work_order
from .test_support import make_profile, order_data


class ArchiveTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username='archive_test', password='fake-only')
        self.profile = make_profile(self.actor)
        self.order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=order_data(zero_filing_approved=True))

    def archive(self, confirmed=True):
        return archive_stopped_order(actor=self.actor, work_order_id=self.order.pk,
            expected_version=self.order.version, confirmed_stopped=confirmed)

    def test_archive_ready_preserves_history_and_blocks_reuse(self):
        self.order = transition_work_order(actor=self.actor, work_order_id=self.order.pk,
            expected_version=self.order.version, target='READY_TO_PREPARE')
        snapshot_id = self.order.current_snapshot_id
        archived = self.archive()
        self.assertTrue(archived.is_archived)
        self.assertEqual(archived.status, 'DRAFT')
        self.assertEqual(archived.current_snapshot_id, snapshot_id)
        self.assertEqual(archived.audit_events.last().changed_fields, ['is_archived'])
        with self.assertRaises(ValidationError):
            validate_readiness(archived)
        with self.assertRaises(ValidationError):
            edit_work_order(actor=self.actor, work_order_id=archived.pk,
                expected_version=archived.version, changes={'filing_quarter': 4})
        self.client.force_login(self.actor)
        self.assertNotContains(self.client.get('/work-orders/'), archived.work_order_id)
        self.assertContains(self.client.get(f'/work-orders/{archived.pk}/'), 'Archived test filing')

    def test_requires_stopped_confirmation(self):
        with self.assertRaises(ValidationError):
            self.archive(False)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)
