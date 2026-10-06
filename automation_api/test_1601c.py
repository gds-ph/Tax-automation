"""Monthly integration contracts; never runs PAD or contacts BIR."""
import json
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from workorders.models import WorkOrder
from workorders.test_support import make_profile
from workorders.services import create_work_order, transition_work_order
from .services import create_agent
from .models import Stage2Approval
from . import stage2, worker_services
from .test_worker_api import WorkerApiTests, two_page_pdf


class MonthlyIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('monthly-test', password='test-only')
        cls.profile = make_profile(cls.actor, key='1601cv2018_zero')
        cls.agent, cls.token = create_agent(actor=cls.actor, name='MONTHLY-TEST')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name, ENABLE_1601C_SUBMISSION=False)
        override.enable()
        self.addCleanup(override.disable)
        self.client.defaults['HTTP_AUTHORIZATION'] = 'Bearer ' + self.token

    upload = WorkerApiTests.upload
    result = WorkerApiTests.result

    def make_order(self, month=1, ready=True):
        order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=dict(filing_year='2026', filing_month=month, zero_filing=True,
                      zero_filing_approved=True, form_data={}))
        if ready:
            order = transition_work_order(work_order_id=order.pk, actor=self.actor,
                expected_version=order.version, target='READY_TO_PREPARE')
        return order

    def prepared(self, month=1):
        order = self.make_order(month)
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1601CV2018_ZERO'])
        data = worker_services.payload(attempt)
        self.assertEqual(self.upload(data).status_code, 200)
        self.assertEqual(self.result(data).status_code, 200)
        order.refresh_from_db()
        return order, data

    def test_monthly_payload_and_result_keep_leading_zeros(self):
        order = self.make_order()
        self.assertIsNone(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_2551QV2018_ZERO']))
        request_id = uuid.uuid4()
        response = self.client.post('/api/agent/preparation/claim/', json.dumps({
            'request_id': str(request_id), 'automation_keys': ['PREPARE_1601CV2018_ZERO']}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        job = response.json()
        self.assertEqual(job['Inputs']['FilingMonth'], '01')
        self.assertEqual(job['Inputs']['FilingQuarter'], '')
        self.assertEqual(job['ExpectedReturnPeriod'], '012026')
        self.assertTrue(job['ExpectedXmlPath'].endswith('00100200300000-1601Cv2018-012026.xml'))
        self.assertTrue(job['ExpectedPdfPath'].endswith('_1601C_2026_01_COMPLETE.pdf'))
        self.assertEqual(order.review_pdf_filename, job['ExpectedPdfPath'].split('\\')[-1])
        with self.assertRaises(worker_services.WorkerError):
            worker_services.claim(agent=self.agent, request_id=request_id,
                automation_keys=['PREPARE_2551QV2018_ZERO'])
        self.assertEqual(self.upload(job).status_code, 200)
        self.assertEqual(self.result(job).status_code, 200)

    def test_monthly_pdf_accepts_print_split_three_pages(self):
        order = self.make_order()
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1601CV2018_ZERO'])
        job = worker_services.payload(attempt)
        response = self.upload(job, data=two_page_pdf(3))
        self.assertEqual(response.status_code, 200, response.content)

    def test_xml_reservation_blocks_same_month_but_not_next_month(self):
        self.prepared()
        with self.assertRaises(ValidationError):
            self.make_order(1)
        order = self.make_order(2)
        self.assertEqual(order.expected_return_period, '022026')

    def test_invalid_period_and_nonzero_are_rejected(self):
        base = dict(filing_year='2026', filing_month=1, zero_filing=True, form_data={})
        for changes in ({'filing_month': 0}, {'filing_month': 13}, {'filing_quarter': 1},
                        {'zero_filing': False}, {'form_data': {'atc_code': 'PT 010'}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
                                  data={**base, **changes})

    def test_live_approval_is_disabled_by_default(self):
        order, _ = self.prepared()
        with self.assertRaisesMessage(ValidationError, 'not enabled'):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                          digest=order.prepared_pdf_sha256, submission_enabled=True)
        self.assertFalse(Stage2Approval.objects.exists())
        browser = Client()
        browser.force_login(self.actor)
        response = browser.get(reverse('workorders:detail', args=[order.pk]))
        self.assertContains(response, '01/2026')
        self.assertContains(response, 'Live submission for this form is not enabled')
        self.assertNotContains(response, 'name="authorize_submission"')

    def test_monthly_stage2_capability_and_duplicate_identity(self):
        with override_settings(ENABLE_1601C_SUBMISSION=True):
            order, _ = self.prepared()
            approval = stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                digest=order.prepared_pdf_sha256, submission_enabled=True)
            self.assertIsNone(stage2.claim_job(self.agent, uuid.uuid4(), [stage2.LIVE_KEY]))
            job = stage2.payload(stage2.claim_job(self.agent, uuid.uuid4(), [stage2.MONTHLY_LIVE_KEY]))
            self.assertEqual(job['AutomationKey'], 'SUBMIT_1601CV2018')
            self.assertEqual(job['Inputs']['ApprovedReturnPeriod'], '012026')
            self.assertEqual(job['Inputs']['ApprovedXmlPath'], order.saved_xml_path)
            # Success without uploaded evidence remains rejected for this form too.
            response = self.client.post(job['ResultUrl'], json.dumps({
                'lease_token': job['LeaseToken'], 'SubmissionStatus': stage2.SUCCESS}), content_type='application/json')
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.client.post(job['ResultUrl'], json.dumps({
                'lease_token': job['LeaseToken'], 'SubmissionStatus': 'BLOCKED_NOT_APPROVED'}),
                content_type='application/json').status_code, 200)
            order.is_archived = True
            order.save(_service_write=True)
            repeat, _ = self.prepared(1)
            with self.assertRaisesMessage(ValidationError, 'already has a submission approval'):
                stage2.approve(actor=self.actor, order_id=repeat.pk, version=repeat.version,
                    digest=repeat.prepared_pdf_sha256, submission_enabled=True)
            next_month, _ = self.prepared(2)
            stage2.approve(actor=self.actor, order_id=next_month.pk, version=next_month.version,
                digest=next_month.prepared_pdf_sha256, submission_enabled=True)

    def test_monthly_prepare_screen_and_edit(self):
        browser = Client()
        browser.force_login(self.actor)
        url = reverse('workorders:client-prepare', args=[self.profile.client_id, self.profile.pk])
        page = browser.get(url)
        self.assertContains(page, 'name="filing_month"')
        self.assertNotContains(page, 'name="filing_quarter"')
        data = dict(request_token=page.context['form']['request_token'].value(),
            filing_year='2026', filing_month='8', filing_mode='ZERO', zero_filing_approved='on')
        response = browser.post(url, data)
        self.assertEqual(response.status_code, 302, response.content)
        order = WorkOrder.objects.get()
        self.assertEqual(order.filing_month, 8)
        self.assertIsNone(order.filing_quarter)
        self.assertEqual(order.form_data, {})
        self.assertContains(browser.get(response.url), '08/2026')
        from workorders.forms import WorkOrderForm
        form = WorkOrderForm(dict(filing_year='2026', filing_month='9', zero_filing='on',
            zero_filing_approved='on', expected_version=order.version), instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.source_data()['filing_month'], 9)
