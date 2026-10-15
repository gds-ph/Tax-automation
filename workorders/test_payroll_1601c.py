import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from .payroll_1601c import MONEY, KEY, normalize, totals
from .test_support import make_profile
from .services import create_work_order, transition_work_order
from .models import WorkOrder
from automation_api import worker_services
from automation_api.services import create_agent


def sample(**changes):
    return {**dict.fromkeys(MONEY, '0.00'), 'schema': '1601c-payroll-v1',
            'payroll_confirmed': True, 'other_exempt_description': '',
            'compensation': '100000.00', 'contributions': '5000.00',
            'below_threshold': '25000.00', 'withheld': '7500.00', **changes}


class PayrollTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser('payroll', password='test-only')
        cls.profile = make_profile(cls.actor, key='1601cv2018_zero')
        cls.agent, _ = create_agent(actor=cls.actor, name='PAYROLL-TEST')

    def order(self, **changes):
        return create_work_order(actor=self.actor, client_filing_profile_id=self.profile.pk,
            data={'filing_year': '2026', 'filing_month': 2, 'zero_filing': False,
                  'zero_filing_approved': False, 'form_data': sample(), **changes})

    def test_totals_and_zero_withholding(self):
        self.assertEqual(totals(normalize(sample())), {'exempt': '5000.00', 'taxable': '95000.00', 'subject': '70000.00', 'due': '7500.00'})
        self.assertEqual(totals(normalize(sample(withheld='0')))['due'], '0.00')

    def test_invalid_amounts_scope_and_reconciliation(self):
        for changes in ({'compensation': '0'}, {'withheld': '-1'}, {'withheld': 'NaN'},
                        {'withheld': '1.001'}, {'contributions': '100001'},
                        {'below_threshold': '100000'}, {'withheld': '80000'},
                        {'other_exempt': '1'}, {'adjustment': '5'}, {'withheld': 0.1}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                normalize(sample(**changes))

    def test_modes_cannot_be_mixed_and_review_is_required(self):
        for changes in ({'zero_filing': True}, {'zero_filing_approved': True}, {'form_data': {}}):
            with self.assertRaises(ValidationError):
                self.order(**changes)
        order = self.order(form_data=sample(payroll_confirmed=False))
        with self.assertRaises(ValidationError):
            transition_work_order(work_order_id=order.pk, actor=self.actor,
                                  expected_version=order.version, target='READY_TO_PREPARE')

    def test_old_worker_cannot_claim_payroll_and_payload_matches_snapshot(self):
        order = self.order()
        transition_work_order(work_order_id=order.pk, actor=self.actor, expected_version=order.version, target='READY_TO_PREPARE')
        self.assertIsNone(worker_services.claim(agent=self.agent, request_id=uuid.uuid4(), automation_keys=['PREPARE_1601CV2018_ZERO']))
        request_id = uuid.uuid4()
        attempt = worker_services.claim(agent=self.agent, request_id=request_id, automation_keys=[KEY])
        payload = worker_services.payload(attempt)
        self.assertEqual(payload['AutomationKey'], KEY)
        self.assertEqual(payload['Inputs']['Payroll'], sample())
        self.assertEqual(payload['Inputs']['PayrollTotals']['due'], '7500.00')
        self.assertEqual(payload['ExpectedReturnPeriod'], '022026')
        with self.assertRaises(worker_services.WorkerError):
            worker_services.claim(agent=self.agent, request_id=request_id, automation_keys=['PREPARE_1601CV2018_ZERO'])

    def test_preview_queue_requires_review_and_is_idempotent(self):
        self.client.force_login(self.actor)
        url = reverse('workorders:payroll-prepare', args=[self.profile.client_id, self.profile.pk])
        response = self.client.post(url, {**sample(), 'filing_year': '2026', 'filing_month': '2', 'scope': 'on', 'action': 'preview'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkOrder.objects.exists())
        token = response.context['preview_token']
        self.assertTrue(token)
        self.assertEqual(self.client.post(url, {'action': 'queue', 'preview_token': token}).status_code, 409)
        post = {'action': 'queue', 'preview_token': token, 'reviewed': 'on', 'withheld': '1'}
        self.assertEqual(self.client.post(url, post).status_code, 302)
        self.assertEqual(self.client.post(url, post).status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), 1)
        self.assertEqual(WorkOrder.objects.get().form_data['withheld'], '7500.00')
        self.assertFalse(WorkOrder.objects.get().zero_filing)

    def test_payroll_never_allows_advance_auto_approval(self):
        from automation_api.auto_approval import request_auto_approval
        with self.assertRaisesMessage(ValidationError, 'manual review'):
            request_auto_approval(actor=self.actor, order=self.order())

    def test_recovery_requires_explicit_operator_release(self):
        order = self.order()
        transition_work_order(work_order_id=order.pk, actor=self.actor,
                              expected_version=order.version, target='READY_TO_PREPARE')
        attempt = worker_services.claim(agent=self.agent, request_id=uuid.uuid4(), automation_keys=[KEY])
        args = dict(agent=self.agent, attempt_id=attempt.pk, lease_token=attempt.lease_token,
                    work_order_id=order.work_order_id, automation_key=KEY)
        self.assertFalse(worker_services.preparation_recovery(**args)['ClearPending'])
        order.refresh_from_db()
        worker_services.abandon(actor=self.actor, attempt_id=attempt.pk,
                                expected_version=order.version, confirmed_stopped=True)
        self.assertTrue(worker_services.preparation_recovery(**args)['ClearPending'])

    def test_review_token_is_bound_to_source_versions(self):
        self.client.force_login(self.actor)
        url = reverse('workorders:payroll-prepare', args=[self.profile.client_id, self.profile.pk])
        response = self.client.post(url, {**sample(), 'filing_year': '2026', 'filing_month': '2', 'scope': 'on', 'action': 'preview'})
        token = response.context['preview_token']
        from django.core import signing
        data = signing.loads(token, salt='1601c-payroll-review-v1')
        data['versions']['client'] += 1
        stale = signing.dumps(data, salt='1601c-payroll-review-v1')
        self.assertEqual(self.client.post(url, {'action': 'queue', 'preview_token': stale, 'reviewed': 'on'}).status_code, 409)
        self.assertFalse(WorkOrder.objects.exists())
