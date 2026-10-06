"""1601EQ contracts. All filings and network calls are test-only."""
import json
import tempfile
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from workorders.test_support import make_profile
from workorders.services import create_work_order, transition_work_order
from workorders.models import WorkOrder
from .services import create_agent
from . import stage2, worker_services
from .test_worker_api import WorkerApiTests, two_page_pdf

class EQIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('eq-test', password='test-only')
        cls.profile = make_profile(cls.actor, key='cor_1601eq')
        cls.agent, cls.token = create_agent(actor=cls.actor, name='EQ-TEST')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name, ENABLE_1601EQ_SUBMISSION=False)
        override.enable()
        self.addCleanup(override.disable)
        self.client.defaults['HTTP_AUTHORIZATION'] = 'Bearer ' + self.token

    upload = WorkerApiTests.upload
    result = WorkerApiTests.result

    def queued(self, quarter=1):
        order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=dict(filing_year='2026', filing_quarter=quarter, zero_filing=True,
                      zero_filing_approved=True, form_data={}))
        return transition_work_order(work_order_id=order.pk, actor=self.actor,
            expected_version=order.version, target='READY_TO_PREPARE')

    def prepared(self):
        order = self.queued()
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1601EQ_ZERO'])
        job = worker_services.payload(attempt)
        self.assertEqual(self.upload(job, data=two_page_pdf(1)).status_code, 200)
        self.assertEqual(self.result(job).status_code, 200)
        order.refresh_from_db()
        return order, job

    def test_preparation_contract_and_one_page_pdf(self):
        order, job = self.prepared()
        self.assertEqual(job['ExpectedReturnPeriod'], '2026Q1')
        self.assertEqual(order.expected_return_period, '2026Q1')
        self.assertTrue(job['ExpectedXmlPath'].endswith('00100200300000-1601EQ-2026Q1.xml'))
        self.assertTrue(job['ExpectedPdfPath'].endswith('_1601EQ_2026_Q1_COMPLETE.pdf'))
        self.assertEqual(job['Inputs']['FilingMonth'], '')
        self.assertEqual(job['Inputs']['FilingQuarter'], '1')
        self.assertEqual(job['Inputs']['ATCCode'], '')
        self.assertEqual(order.review_pdf_filename, job['ExpectedPdfPath'].split('\\')[-1])
        with self.assertRaises(ValidationError):
            self.queued(1)
        self.queued(2)

    def test_other_worker_cannot_claim_and_two_page_pdf_rejected(self):
        self.queued()
        self.assertIsNone(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1601CV2018_ZERO']))
        job = worker_services.payload(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1601EQ_ZERO']))
        self.assertNotEqual(self.upload(job, data=two_page_pdf(2)).status_code, 200)

    def test_submission_gated_and_requires_screenshot_evidence(self):
        order, _ = self.prepared()
        with self.assertRaisesMessage(ValidationError, 'not enabled'):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                digest=order.prepared_pdf_sha256, submission_enabled=True)
        with override_settings(ENABLE_1601EQ_SUBMISSION=True):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                digest=order.prepared_pdf_sha256, submission_enabled=True)
            self.assertIsNone(stage2.claim_job(self.agent, uuid.uuid4(), [stage2.MONTHLY_LIVE_KEY]))
            job = stage2.payload(stage2.claim_job(self.agent, uuid.uuid4(), [stage2.EQ_LIVE_KEY]))
            self.assertEqual(job['AutomationKey'], 'SUBMIT_1601EQ')
            self.assertEqual(job['Inputs']['ApprovedReturnPeriod'], '2026Q1')
            self.assertEqual(job['Inputs']['ApprovedXmlPath'], order.saved_xml_path)
            response = self.client.post(job['ResultUrl'], json.dumps({
                'lease_token': job['LeaseToken'], 'SubmissionStatus': stage2.SUCCESS}), content_type='application/json')
            self.assertEqual(response.status_code, 409)

    def test_prepare_page_and_edit_have_no_atc(self):
        self.client.force_login(self.actor)
        url=reverse('workorders:client-prepare', args=[self.profile.client_id,self.profile.pk])
        page=self.client.get(url)
        self.assertContains(page, 'name="filing_quarter"')
        self.assertContains(page, 'non-amended private-agent')
        data=dict(request_token=page.context['form']['request_token'].value(), filing_year='2026',
            filing_quarter='1', filing_mode='ZERO', zero_filing_approved='on')
        response=self.client.post(url,data)
        self.assertEqual(response.status_code,302)
        order=WorkOrder.objects.get()
        self.assertEqual(order.form_data,{})
        self.assertEqual(self.client.get(response.url).status_code,200)
        from workorders.forms import WorkOrderForm
        form=WorkOrderForm(dict(filing_year='2026',filing_quarter='2',zero_filing='on',
            zero_filing_approved='on',expected_version=order.version),instance=order)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.source_data()['form_data'],{})

    def test_unsupported_inputs_rejected(self):
        base=dict(filing_year='2026',filing_quarter=1,zero_filing=True,form_data={})
        for changes in ({'filing_quarter':5},{'filing_month':1},{'zero_filing':False},
                        {'form_data':{'atc_code':'PT 010'}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                create_work_order(actor=self.actor,client_filing_profile_id=self.profile.pk,data={**base,**changes})
