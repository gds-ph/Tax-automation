import json
import uuid
from django.urls import reverse
from django.test import Client
from django.core.exceptions import ValidationError
from .test_worker_api import WorkerApiTests
from .stage2 import approve, claim_job, payload
from .models import Stage2Approval
from .worker_services import WorkerError, private_pdf_path
from workorders.models import WorkOrder


class Stage2Tests(WorkerApiTests):
    def prepared(self):
        job=self.job(); self.upload(job); self.result(job)
        order=WorkOrder.objects.get()
        approval=approve(actor=self.actor, order_id=order.pk, version=order.version, digest=order.prepared_pdf_sha256)
        return order, approval

    def test_stage2_claim_replay_and_result(self):
        order, approval=self.prepared()
        self.assertIsNone(claim_job(self.other, uuid.uuid4()))
        request_id=uuid.uuid4()
        claimed=claim_job(self.agent, request_id)
        data=payload(claimed)
        self.assertEqual(data['Inputs']['ApprovalId'], str(approval.pk))
        self.assertFalse(data['Inputs']['SubmissionEnabled'])
        self.assertEqual(data['ExpectedPdfPath'], order.prepared_pdf_vm_path)
        self.assertEqual(claim_job(self.agent, request_id).attempt_id, request_id)
        self.assertEqual(self.claim().status_code, 409)
        with self.assertRaises(WorkerError):
            claim_job(self.other, request_id)
        url=data['ResultUrl']
        def report(status):
            return self.client.post(url, json.dumps({'lease_token':data['LeaseToken'], 'SubmissionStatus':status}), content_type='application/json')
        self.assertEqual(report('SUBMITTED').status_code, 400)
        self.assertEqual(report('APPROVED_READY_TO_SUBMIT').status_code, 200)
        self.assertEqual(report('APPROVED_READY_TO_SUBMIT').status_code, 200)
        self.assertEqual(report('FAILED_SYSTEM').status_code, 409)
        order.refresh_from_db()
        self.assertFalse(order.approved_for_submission)
        self.assertEqual(order.status,'AWAITING_SUBMISSION_APPROVAL')

    def test_stage2_tampered_pdf_and_stale_approval(self):
        order, approval=self.prepared()
        with self.assertRaises(ValidationError):
            approve(actor=self.actor, order_id=order.pk, version=order.version-1, digest=order.prepared_pdf_sha256)
        private_pdf_path(order).write_bytes(b'changed')
        with self.assertRaises(WorkerError):
            claim_job(self.agent, uuid.uuid4())
        self.assertEqual(Stage2Approval.objects.get().state, 'QUEUED')

    def test_approval_csrf_and_permission(self):
        order, approval=self.prepared()
        url=reverse('workorders:approve-stage2',args=[order.pk])
        browser=Client(enforce_csrf_checks=True)
        browser.force_login(self.actor)
        self.assertEqual(browser.post(url,{}).status_code,403)
        self.assertEqual(Client().post(url,{}).status_code,302)
