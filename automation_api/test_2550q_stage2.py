import base64
import hashlib
import json
import uuid
from django.test import TestCase, Client, override_settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from . import test_2550q as preparation
from . import test_worker_api as fixtures
from . import stage2
from .models import Stage2Approval, AutoSubmissionConsent
from .auto_approval import request_auto_approval
from workorders.test_support import make_profile


@override_settings(ENABLE_2550Q_SUBMISSION=True)
class Submission2550QTests(TestCase):
    setUpTestData = classmethod(fixtures.WorkerApiTests.setUpTestData.__func__)
    setUp = fixtures.WorkerApiTests.setUp
    job = preparation.Preparation2550QTests.job
    upload = fixtures.WorkerApiTests.upload
    result = fixtures.WorkerApiTests.result

    def prepared(self):
        order, job = self.job()
        self.assertEqual(self.upload(job).status_code,200)
        self.assertEqual(self.result(job).status_code,200)
        order.refresh_from_db()
        return order

    def approve(self, order):
        return stage2.approve(actor=self.actor,order_id=order.pk,version=order.version,
            digest=order.prepared_pdf_sha256,submission_enabled=True)

    def test_contract_and_evidence_required_for_success(self):
        order=self.prepared(); approval=self.approve(order)
        self.assertIsNone(stage2.claim_job(self.agent,uuid.uuid4(),['SUBMIT_2551QV2018']))
        self.assertIsNone(stage2.claim_job(self.other,uuid.uuid4(),['SUBMIT_2550QV2024']))
        claimed=stage2.claim_job(self.agent,uuid.uuid4(),['SUBMIT_2550QV2024'])
        data=stage2.payload(claimed); inputs=data['Inputs']
        self.assertEqual(data['AutomationKey'],'SUBMIT_2550QV2024')
        self.assertEqual(inputs['ApprovedReturnPeriod'],'2026Q3')
        computed=''.join(inputs[k] for k in ('TIN1','TIN2','TIN3','TIN4'))+'-'+inputs['ExpectedFormNumber']+'-'+inputs['YearEndMonth']+inputs['ApprovedReturnPeriod']
        self.assertEqual(computed,inputs['ApprovedSavedReturnName'])
        self.assertTrue(inputs['ApprovedXmlPath'].endswith(computed+'.xml'))
        self.assertEqual(inputs['FilingMonth'],'')
        def report():
            return self.client.post(data['ResultUrl'],json.dumps({'lease_token':data['LeaseToken'],'SubmissionStatus':stage2.SUCCESS}),content_type='application/json')
        self.assertEqual(report().status_code,409)
        image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        response=self.client.put(data['ScreenshotUploadUrl'],image,content_type='image/png',HTTP_X_LEASE_TOKEN=data['LeaseToken'],HTTP_X_SCREENSHOT_SHA256=hashlib.sha256(image).hexdigest())
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(report().status_code,200)
        self.assertEqual(report().status_code,200)
        approval.refresh_from_db();self.assertEqual(approval.state,stage2.SUCCESS)
        from .receipts import discover_pending
        discover_pending()
        self.assertTrue(approval.receipt_check.filename.endswith('-2550Qv2024-122026Q3.xml'))

    def test_flag_blocks_approval_and_revalidation_never_queues(self):
        order=self.prepared()
        with override_settings(ENABLE_2550Q_SUBMISSION=False):
            with self.assertRaises(ValidationError): self.approve(order)
        with self.assertRaises(ValidationError):
            stage2.approve(actor=self.actor,order_id=order.pk,version=order.version,digest=order.prepared_pdf_sha256)
        self.assertFalse(Stage2Approval.objects.exists())

    def test_auto_approval_and_ui_when_enabled(self):
        order,job=self.job()
        request_auto_approval(actor=self.actor,order=order)
        self.assertEqual(self.upload(job).status_code,200)
        self.assertEqual(self.result(job).status_code,200)
        self.assertEqual(AutoSubmissionConsent.objects.get(work_order=order).state,'APPLIED')
        self.assertTrue(Stage2Approval.objects.get(work_order=order).submission_enabled)
        browser=Client();browser.force_login(self.actor)
        url=reverse('workorders:client-prepare',args=[order.client_id,order.client_filing_profile_id])
        self.assertContains(browser.get(url),'name="auto_approve"')
