from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from unittest.mock import patch
from .auto_approval import apply_auto_approval
from . import test_worker_api as worker_tests
from .models import AutoSubmissionConsent, Stage2Approval
from .auto_approval import request_auto_approval


class AutoApprovalTests(TestCase):
    setUpTestData = classmethod(worker_tests.WorkerApiTests.setUpTestData.__func__)
    setUp = worker_tests.WorkerApiTests.setUp
    make_order = worker_tests.WorkerApiTests.make_order
    claim = worker_tests.WorkerApiTests.claim
    upload = worker_tests.WorkerApiTests.upload
    result = worker_tests.WorkerApiTests.result

    def prepare(self, opted_in=True):
        order = self.make_order()
        if opted_in:
            request_auto_approval(actor=self.actor, order=order)
        job = self.claim().json()
        self.assertEqual(self.upload(job).status_code, 200)
        return order, job

    def test_success_queues_live_submission_once(self):
        order, job = self.prepare()
        response = self.result(job)
        self.assertEqual(response.status_code, 200, response.content)
        approval = Stage2Approval.objects.get(work_order=order)
        self.assertTrue(approval.submission_enabled)
        self.assertEqual(approval.snapshot_id, order.current_snapshot_id)
        self.assertEqual(approval.approved_by_id, self.actor.pk)
        self.assertIn('advance authorization', approval.comment)
        self.assertEqual(AutoSubmissionConsent.objects.get(work_order=order).state, 'APPLIED')
        response = self.result(job)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Stage2Approval.objects.filter(work_order=order).count(), 1)

    def test_default_keeps_manual_approval(self):
        order, job = self.prepare(False)
        response = self.result(job)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Stage2Approval.objects.filter(work_order=order).exists())

    def test_revoked_actor_blocks_automatic_approval_without_losing_pdf(self):
        order, job = self.prepare()
        self.actor.is_active = False
        self.actor.save()
        response = self.result(job)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AutoSubmissionConsent.objects.get(work_order=order).state, 'BLOCKED')
        self.assertFalse(Stage2Approval.objects.filter(work_order=order).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, 'AWAITING_SUBMISSION_APPROVAL')
        self.assertTrue(order.prepared_pdf_sha256)

    def test_failed_preparation_never_approves(self):
        order, job = self.prepare()
        response = self.result(job, PreparationStatusOutput='FAILED_SYSTEM', PreparedPdfPath='', SavedXmlPath='')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AutoSubmissionConsent.objects.get(work_order=order).state, 'BLOCKED')
        self.assertFalse(Stage2Approval.objects.filter(work_order=order).exists())

    def test_unauthorized_consent_rejected(self):
        order = self.make_order()
        self.actor.is_superuser = False
        self.actor.save()
        with self.assertRaises(PermissionDenied):
            request_auto_approval(actor=self.actor, order=order)
        self.assertFalse(AutoSubmissionConsent.objects.exists())

    def test_changed_pdf_cannot_be_approved(self):
        order, job = self.prepare()
        order.refresh_from_db()
        with open(order.prepared_pdf.path, 'ab') as output:
            output.write(b'changed')
        self.assertNotEqual(self.result(job).status_code, 200)
        self.assertFalse(Stage2Approval.objects.filter(work_order=order).exists())

    def test_changed_snapshot_blocks_approval(self):
        order, job = self.prepare()
        with patch('automation_api.auto_approval.apply_auto_approval'):
            self.assertEqual(self.result(job).status_code, 200)
        order.refresh_from_db()
        order.current_snapshot_id = None
        apply_auto_approval(order)
        self.assertEqual(AutoSubmissionConsent.objects.get(work_order=order).state, 'BLOCKED')
        self.assertFalse(Stage2Approval.objects.filter(work_order=order).exists())

    def test_duplicate_return_cannot_be_prepared_again(self):
        first, job = self.prepare()
        self.assertEqual(self.result(job).status_code, 200)
        with self.assertRaisesMessage(ValidationError, 'already reserves this XML filename'):
            self.prepare()
        self.assertEqual(Stage2Approval.objects.count(), 1)

    def test_forged_checkbox_without_permission_is_not_accepted(self):
        from workorders.client_views import PreparationForm
        form = PreparationForm(data={'auto_approve': 'on'}, can_auto_approve=False)
        form.is_valid()
        self.assertNotIn('auto_approve', form.fields)
        self.assertNotIn('auto_approve', form.cleaned_data)
