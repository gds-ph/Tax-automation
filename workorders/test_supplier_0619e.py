import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from .test_support import make_profile
from .models import WorkOrder, ExpandedWithholdingDraft
from .services import create_work_order, transition_work_order
from .supplier_0619e import normalize, withholding, KEY, SCHEMA
from automation_api import worker_services
from automation_api.services import create_agent


def rows():
    return [dict(payee='SAMPLE SUPPLIER', tin='001-002-003-00000', atc='WC120',
                 base='100000.00', rate='2', tax='2000.00', reference='Sample only')]


class SupplierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('supplier-test', password='test-only')
        cls.profile = make_profile(cls.actor, key='0619e_zero')
        from .catalog_services import update_record
        form = cls.profile.form_definition
        update_record(model=type(form), pk=form.pk, actor=cls.actor, expected_version=form.version, changes={'preparation_automation_available': True})
        cls.agent, _ = create_agent(actor=cls.actor, name='SUPPLIER-TEST')
        cls.draft = ExpandedWithholdingDraft.objects.create(client=cls.profile.client, year=2025, month=7, rows=rows(), total='2000.00')

    def data(self, **changes):
        return dict(schema=SCHEMA, rows=rows(), schedule_confirmed=True,
                    draft_id=str(self.draft.pk), draft_version=1, **changes)

    def order(self, **changes):
        return create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data=dict(filing_year='2025', filing_month=7, zero_filing=False,
                      zero_filing_approved=False, form_data=self.data()) | changes)

    def test_amounts_and_rejections(self):
        self.assertEqual(withholding(self.data()), '2000.00')
        for updates in ({'rows': []}, {'rows': 'invalid'}, {'schedule_confirmed': 1},
                        {'rows': [rows()[0] | {'tax': '1999'}]}, {'rows': [rows()[0] | {'base': '-1'}]},
                        {'rows': [rows()[0] | {'base': 'NaN'}]}, {'rows': [rows()[0] | {'base': '0', 'tax': '0'}]},
                        {'penalties': '1'}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                normalize(self.data() | updates)

    def test_mode_review_and_period_guards(self):
        for changes in ({'zero_filing': True}, {'zero_filing_approved': True}, {'form_data': {}}, {'filing_month': 9}):
            with self.assertRaises(ValidationError):
                self.order(**changes)
        order = self.order(form_data=self.data() | {'schedule_confirmed': False})
        with self.assertRaises(ValidationError):
            transition_work_order(work_order_id=order.pk, actor=self.actor, expected_version=order.version, target='READY_TO_PREPARE')

    def test_worker_capability_and_immutable_payload(self):
        order = self.order()
        transition_work_order(work_order_id=order.pk, actor=self.actor, expected_version=order.version, target='READY_TO_PREPARE')
        self.assertIsNone(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(), automation_keys=['PREPARE_0619E_ZERO']))
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(), automation_keys=[KEY])
        self.draft.rows = [rows()[0] | {'tax': '1'}]
        self.draft.save()
        result = worker_services.payload(attempt)
        self.assertEqual(result['Inputs']['WithholdingTotal'], '2000.00')
        self.assertEqual(result['Inputs']['SupplierSchedule']['rows'], rows())
        self.assertEqual(result['ExpectedReturnPeriod'], '072025')

    def test_review_queue_idempotence_and_tampering(self):
        self.client.force_login(self.actor)
        url = reverse('workorders:supplier-prepare', args=[self.profile.client_id, self.draft.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        token = response.context['preview_token']
        self.assertEqual(self.client.post(url, {'preview_token': token}).status_code, 409)
        post = {'preview_token': token, 'reviewed': 'on', 'WithholdingTotal': '1', 'year': '2030'}
        self.assertEqual(self.client.post(url, post).status_code, 302)
        self.assertEqual(self.client.post(url, post).status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), 1)
        self.assertEqual(withholding(WorkOrder.objects.get().form_data), '2000.00')

    def test_stale_draft_review_is_rejected(self):
        self.client.force_login(self.actor)
        url = reverse('workorders:supplier-prepare', args=[self.profile.client_id, self.draft.pk])
        token = self.client.get(url).context['preview_token']
        ExpandedWithholdingDraft.objects.filter(pk=self.draft.pk).update(version=2)
        self.assertEqual(self.client.post(url, {'preview_token': token, 'reviewed': 'on'}).status_code, 409)
        self.assertFalse(WorkOrder.objects.exists())

    def test_manual_approval_required(self):
        from automation_api.auto_approval import request_auto_approval
        with self.assertRaisesMessage(ValidationError, 'manual review'):
            request_auto_approval(actor=self.actor, order=self.order())

    def test_zero_still_claims_without_supplier_amounts(self):
        order = self.order(zero_filing=True, zero_filing_approved=True, form_data={})
        transition_work_order(work_order_id=order.pk, actor=self.actor, expected_version=order.version, target='READY_TO_PREPARE')
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(), automation_keys=['PREPARE_0619E_ZERO'])
        self.assertNotIn('SupplierSchedule', worker_services.payload(attempt)['Inputs'])
