"""1600VT contracts. All filings and network calls are test-only."""
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

class VATWithholdingIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('final-test', password='test-only')
        cls.profile = make_profile(cls.actor, key='1600vt_zero')
        from workorders.catalog_services import update_record
        from workorders.models import FormDefinition
        form = cls.profile.form_definition
        update_record(model=FormDefinition, pk=form.pk, actor=cls.actor, expected_version=form.version, changes={'preparation_automation_available': True})
        cls.agent, cls.token = create_agent(actor=cls.actor, name='FINAL-TEST')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name, ENABLE_1600VT_SUBMISSION=False)
        override.enable()
        self.addCleanup(override.disable)
        self.client.defaults['HTTP_AUTHORIZATION'] = 'Bearer ' + self.token

    upload = WorkerApiTests.upload
    result = WorkerApiTests.result

    def queued(self, month=2):
        order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=dict(filing_year='2026', filing_month=month, zero_filing=True,
                      zero_filing_approved=True, form_data={}))
        return transition_work_order(work_order_id=order.pk, actor=self.actor,
            expected_version=order.version, target='READY_TO_PREPARE')

    def prepared(self):
        order = self.queued()
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1600VT_ZERO'])
        job = worker_services.payload(attempt)
        self.assertEqual(self.upload(job, data=two_page_pdf(1)).status_code, 200)
        self.assertEqual(self.result(job).status_code, 200)
        order.refresh_from_db()
        return order, job

    def test_preparation_contract_and_one_page_pdf(self):
        order, job = self.prepared()
        self.assertEqual(job['ExpectedReturnPeriod'], '022026')
        self.assertEqual(order.expected_return_period, '022026')
        self.assertTrue(job['ExpectedXmlPath'].endswith('00100200300000-1600VTv2018-022026.xml'))
        self.assertTrue(job['ExpectedPdfPath'].endswith('_1600VT_2026_02_COMPLETE.pdf'))
        self.assertEqual(job['Inputs']['FilingMonth'], '02')
        self.assertEqual(job['Inputs']['FilingQuarter'], '')
        self.assertEqual(job['Inputs']['ATCCode'], '')
        self.assertEqual(order.review_pdf_filename, job['ExpectedPdfPath'].split('\\')[-1])
        with self.assertRaises(ValidationError):
            self.queued(2)
        self.queued(3)

    def test_other_worker_cannot_claim_and_two_page_pdf_rejected(self):
        self.queued()
        self.assertIsNone(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1601CV2018_ZERO']))
        job = worker_services.payload(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
            automation_keys=['PREPARE_1600VT_ZERO']))
        self.assertNotEqual(self.upload(job, data=two_page_pdf(2)).status_code, 200)

    def test_submission_gated_and_requires_screenshot_evidence(self):
        order, _ = self.prepared()
        with self.assertRaisesMessage(ValidationError, 'not enabled'):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                digest=order.prepared_pdf_sha256, submission_enabled=True)
        with self.assertRaisesMessage(ValidationError, 'separately'):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version, digest=order.prepared_pdf_sha256)
        with override_settings(ENABLE_1600VT_SUBMISSION=True):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                digest=order.prepared_pdf_sha256, submission_enabled=True)
            self.assertIsNone(stage2.claim_job(self.agent, uuid.uuid4(), [stage2.MONTHLY_LIVE_KEY]))
            job = stage2.payload(stage2.claim_job(self.agent, uuid.uuid4(), [stage2.VT_LIVE_KEY]))
            self.assertEqual(job['AutomationKey'], 'SUBMIT_1600VT')
            self.assertEqual(job['Inputs']['ApprovedReturnPeriod'], '022026')
            self.assertEqual(job['Inputs']['ApprovedSavedReturnName'], '00100200300000-1600VTv2018-022026')
            self.assertEqual(job['Inputs']['FilingMonth'], '02')
            self.assertEqual(job['Inputs']['ApprovedXmlPath'], order.saved_xml_path)
            response = self.client.post(job['ResultUrl'], json.dumps({
                'lease_token': job['LeaseToken'], 'SubmissionStatus': stage2.SUCCESS}), content_type='application/json')
            self.assertEqual(response.status_code, 409)

    def test_prepared_order_visible_in_dashboard(self):
        order, _ = self.prepared()
        self.client.force_login(self.actor)
        from workorders.views import _orders
        self.assertTrue(_orders().filter(pk=order.pk).exists())
