"""Offline-only 1601FQ contracts; no PAD execution or BIR transmission."""
import tempfile
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from workorders.test_support import make_profile
from workorders.catalog_services import update_record
from workorders.models import FormDefinition
from workorders.services import create_work_order, transition_work_order
from .services import create_agent
from . import stage2, worker_services
from . import test_worker_api as fixtures


class FinalQuarterlyIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('fq-test', password='test-only')
        cls.profile = make_profile(cls.actor, key='1601fq_zero')
        form = cls.profile.form_definition
        update_record(model=FormDefinition, pk=form.pk, actor=cls.actor,
                      expected_version=form.version, changes={'preparation_automation_available': True})
        cls.agent, cls.token = create_agent(actor=cls.actor, name='FQ-TEST')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(MEDIA_ROOT=folder.name)
        override.enable()
        self.addCleanup(override.disable)
        self.client.defaults['HTTP_AUTHORIZATION'] = 'Bearer ' + self.token

    upload = fixtures.WorkerApiTests.upload
    result = fixtures.WorkerApiTests.result

    def queued(self, quarter=3, **changes):
        data = dict(filing_year='2026', filing_quarter=quarter, zero_filing=True,
                    zero_filing_approved=True, form_data={})
        data.update(changes)
        order = create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk, data=data)
        return transition_work_order(work_order_id=order.pk, actor=self.actor,
                                     expected_version=order.version, target='READY_TO_PREPARE')

    def test_preparation_identity_pdf_and_submission_block(self):
        order = self.queued()
        self.assertIsNone(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
                                                automation_keys=['PREPARE_0619F_ZERO']))
        job = worker_services.payload(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(),
                                                            automation_keys=['PREPARE_1601FQ_ZERO']))
        self.assertEqual(job['ExpectedReturnPeriod'], '2026Q3')
        self.assertEqual(order.expected_return_period, '2026Q3')
        self.assertTrue(job['ExpectedXmlPath'].endswith('00100200300000-1601FQ-2026Q3.xml'))
        self.assertTrue(job['ExpectedPdfPath'].endswith('_1601FQ_2026_Q3_COMPLETE.pdf'))
        self.assertEqual(job['Inputs']['FilingMonth'], '')
        self.assertEqual(job['Inputs']['FilingQuarter'], '3')
        self.assertEqual(job['Inputs']['ATCCode'], '')
        self.assertNotEqual(self.upload(job, data=fixtures.two_page_pdf(1)).status_code, 200)
        self.assertEqual(self.upload(job, data=fixtures.two_page_pdf(2)).status_code, 200)
        self.assertEqual(self.result(job).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'AWAITING_SUBMISSION_APPROVAL')
        from workorders.views import _orders
        self.assertTrue(_orders().filter(pk=order.pk).exists())
        with self.assertRaises(ValidationError):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                           digest=order.prepared_pdf_sha256, submission_enabled=True)
        with self.assertRaises(ValidationError):
            stage2.approve(actor=self.actor, order_id=order.pk, version=order.version,
                           digest=order.prepared_pdf_sha256)
        with self.assertRaises(ValidationError):
            self.queued()
        self.queued(2)

    def test_nonzero_and_unreviewed_filings_rejected(self):
        for changes in ({'zero_filing': False}, {'zero_filing_approved': False},
                        {'form_data': {'withholding': '1.00'}}):
            with self.assertRaises(ValidationError):
                self.queued(**changes)
