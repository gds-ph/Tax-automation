import json
import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from . import test_worker_api as fixtures
from . import stage2
from .models import Stage2Approval
from workorders.test_support import make_profile, order_data
from workorders.services import create_work_order, transition_work_order
from workorders.models import WorkOrder, FormDefinition


@override_settings(ENABLE_2550Q_SUBMISSION=False)
class Preparation2550QTests(TestCase):
    setUpTestData = classmethod(fixtures.WorkerApiTests.setUpTestData.__func__)
    setUp = fixtures.WorkerApiTests.setUp
    upload = fixtures.WorkerApiTests.upload
    result = fixtures.WorkerApiTests.result

    def job(self):
        profile = make_profile(self.actor, key='2550qv2024_zero')
        order = create_work_order(actor=self.actor, client_filing_profile_id=profile.pk,
            data=order_data(form_data={}, zero_filing_approved=True))
        transition_work_order(work_order_id=order.pk, actor=self.actor, expected_version=order.version, target='READY_TO_PREPARE')
        response = self.client.post(reverse('automation_api:claim'), data=json.dumps({
            'request_id': str(uuid.uuid4()), 'automation_keys': ['PREPARE_2550QV2024_ZERO']}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return order, response.json()

    def test_payload_pdf_result_and_dashboard_match_pad(self):
        order, job = self.job()
        self.assertEqual(job['Inputs']['FormCode'], '2550Qv2024')
        self.assertEqual(job['Inputs']['ExpectedFormNumber'], '2550Qv2024')
        self.assertEqual(job['Inputs']['FilingMonth'], '')
        self.assertEqual(job['Inputs']['FilingQuarter'], '3')
        self.assertEqual(job['Inputs']['ATCCode'], '')
        self.assertEqual(job['ExpectedReturnPeriod'], '122026Q3')
        self.assertTrue(job['ExpectedXmlPath'].endswith('-2550Qv2024-122026Q3.xml'))
        self.assertTrue(job['ExpectedPdfPath'].endswith('_2550Qv2024_2026_Q3_COMPLETE.pdf'))
        self.assertEqual(self.upload(job).status_code, 200)
        self.assertEqual(self.result(job).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'AWAITING_SUBMISSION_APPROVAL')
        browser = Client(); browser.force_login(self.actor)
        self.assertContains(browser.get(reverse('workorders:detail', args=[order.pk])), 'Live submission for this form is not enabled yet')
        for enabled in (False, True):
            with self.assertRaises(ValidationError):
                stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                    digest=order.prepared_pdf_sha256, submission_enabled=enabled)
        self.assertFalse(Stage2Approval.objects.exists())

    def test_wrong_page_count_rejected(self):
        order, job = self.job()
        self.assertNotEqual(self.upload(job, fixtures.two_page_pdf(pages=1)).status_code, 200)
        self.assertNotEqual(self.result(job).status_code, 200)

    def test_ui_confirmation_and_no_auto_submission(self):
        profile = make_profile(self.actor, key='2550qv2024_zero')
        browser = Client(); browser.force_login(self.actor)
        url = reverse('workorders:client-prepare', args=[profile.client_id, profile.pk])
        response = browser.get(url)
        self.assertContains(response, 'Micro taxpayer')
        self.assertNotContains(response, 'name="auto_approve"')
        response = browser.post(url, dict(request_token=response.context['form']['request_token'].value(),
            filing_mode='ZERO', filing_year='2026', filing_quarter='3', zero_filing_approved='on', auto_approve='on'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkOrder.objects.get().form_data, {})

    def test_fiscal_and_amounts_rejected(self):
        with self.assertRaises(ValidationError):
            make_profile(self.actor, key='2550qv2024_zero', calendar_or_fiscal='FISCAL', year_end_month='06')
        profile = make_profile(self.actor, key='2550qv2024_zero')
        for data in (order_data(form_data={'sales': 100}), order_data(form_data={}, zero_filing=False)):
            with self.assertRaises(ValidationError):
                create_work_order(actor=self.actor, client_filing_profile_id=profile.pk, data=data)
