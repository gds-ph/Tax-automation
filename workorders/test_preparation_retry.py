import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from automation_api import worker_services
from automation_api.services import create_agent
from . import services
from .test_support import make_profile, order_data


class PreparationRetryTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('retry_admin')
        self.user = get_user_model().objects.create_user('retry_preparer')
        self.user.groups.add(Group.objects.get(name='Preparer'))
        profile = make_profile(self.admin, key='0619f_zero')
        from .catalog_services import update_record
        from .models import FormDefinition
        update_record(model=FormDefinition, pk=profile.form_definition_id, actor=self.admin,
                      expected_version=profile.form_definition.version,
                      changes={'preparation_automation_available': True})
        self.order = services.create_work_order(actor=self.user, client_filing_profile_id=profile.pk,
            data=order_data(filing_quarter=None, filing_month=2, form_data={}, zero_filing_approved=True))
        self.order = services.transition_work_order(work_order_id=self.order.pk, actor=self.user,
            expected_version=self.order.version, target='READY_TO_PREPARE')
        self.agent, _ = create_agent(actor=self.admin, name='retry_vm')
        self.attempt = self.claim()
        self.order.refresh_from_db()
        self.client.force_login(self.user)
        self.url = reverse('workorders:retry', args=[self.order.pk])

    def claim(self):
        return worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
                                     automation_keys=['PREPARE_0619F_ZERO'])

    def fail(self):
        worker_services.record_result(agent=self.agent, attempt_id=self.attempt.pk,
            lease_token=self.attempt.lease_token, data={'PreparationStatusOutput': 'FAILED_SYSTEM'})
        self.order.refresh_from_db()

    def retry(self):
        return services.retry_preparation(work_order_id=self.order.pk, actor=self.user,
                                          expected_version=self.order.version)

    def test_retry_keeps_history_and_claims_new_attempt(self):
        self.fail()
        snapshot = self.order.current_snapshot_id
        old_version = self.order.version
        self.assertContains(self.client.get(reverse('workorders:detail', args=[self.order.pk])), 'Retry preparation')
        response = self.client.post(self.url, {'expected_version': old_version})
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'READY_TO_PREPARE')
        self.assertEqual(self.order.current_snapshot_id, snapshot)
        self.assertEqual(self.order.attempt_count, 1)
        self.assertFalse(self.order.error_code)
        self.assertIsNone(self.order.lease_token)
        self.assertEqual(self.client.post(self.url, {'expected_version': old_version}).status_code, 409)
        new_attempt = self.claim()
        self.assertNotEqual(new_attempt.pk, self.attempt.pk)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, 'FAILED')
        self.order.refresh_from_db()
        self.assertEqual(self.order.attempt_count, 2)
        # An old result replay must not overwrite the newly running preparation.
        worker_services.record_result(agent=self.agent, attempt_id=self.attempt.pk,
            lease_token=self.attempt.lease_token, data={'PreparationStatusOutput': 'FAILED_SYSTEM'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PROCESSING_PREPARATION')

    def test_interrupted_attempt_requires_release_first(self):
        with self.assertRaises(ValidationError):
            self.retry()
        worker_services.abandon(actor=self.admin, attempt_id=self.attempt.pk,
                               expected_version=self.order.version, confirmed_stopped=True)
        self.order.refresh_from_db()
        self.retry()
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, 'ABANDONED')

    def test_stale_configuration_rejects_retry(self):
        self.fail()
        from .catalog_services import update_record
        update_record(model=type(self.order.client), pk=self.order.client_id, actor=self.admin,
                      expected_version=self.order.client.version, changes={'trade_name': 'Updated client'})
        with self.assertRaises(ValidationError):
            self.retry()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'FAILED_SYSTEM')

    def test_existing_evidence_and_archives_require_review(self):
        self.fail()
        for field, value in [('prepared_pdf', 'existing.pdf'), ('is_archived', True), ('saved_xml_path', 'existing.xml')]:
            with self.subTest(field=field):
                self.order.refresh_from_db()
                setattr(self.order, field, value)
                self.assertTrue(services.preparation_retry_blocker(self.order))

    def test_post_permission_and_csrf_required(self):
        self.fail()
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url, {'expected_version': self.order.version}).status_code, 403)
        viewer = get_user_model().objects.create_user('retry_viewer')
        viewer.groups.add(Group.objects.get(name='Approver'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(self.url, {'expected_version': self.order.version}).status_code, 403)
        self.assertNotContains(self.client.get(reverse('workorders:detail', args=[self.order.pk])), 'Retry preparation')

    def test_worker_update_download_is_operator_only(self):
        import io
        import zipfile
        url = reverse('workorders:worker-recovery-update')
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as package:
            self.assertIn('Install-DashboardRecovery.cmd', package.namelist())
            self.assertIn(b'ClearPending', package.read('WorkerBridge.ps1'))

    def test_release_cannot_target_another_filings_attempt(self):
        other = services.create_work_order(actor=self.user,
            client_filing_profile_id=self.order.client_filing_profile_id,
            data=order_data(filing_quarter=None, filing_month=3, form_data={}, zero_filing_approved=True))
        self.client.force_login(self.admin)
        response = self.client.post(reverse('workorders:release-interrupted', args=[other.pk]),
            {'confirmed_stopped': 'on', 'attempt_id': str(self.attempt.pk), 'version': self.order.version})
        self.assertEqual(response.status_code, 409)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.state, 'RUNNING')
