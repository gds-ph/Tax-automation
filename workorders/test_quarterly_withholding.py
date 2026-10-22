from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from .quarterly_withholding import calculate
from .quarterly_models import QuarterlyWithholdingDraft
from .models import WorkOrder, ExpandedWithholdingDraft
from .test_support import make_profile


def row(**changes):
    return dict(month=7, payee='TEST SUPPLIER', tin='001-002-003-00000', atc='WC120', base='100,000.00', reference='TEST', **changes)


class ArithmeticTests(SimpleTestCase):
    def test_full_quarter_groups_and_actual_payments(self):
        rows = [row(), {**row(), 'month': 8}, {**row(), 'month': 9}]
        result = calculate(rows, 3, '2,000.00', '2,000.00')
        self.assertEqual(result['withheld'], '6000.00')
        self.assertEqual(result['due'], '2000.00')
        self.assertEqual(result['groups'][0]['base'], '300000.00')

    def test_forged_rate_ignored_and_month_checked(self):
        self.assertEqual(calculate([{**row(), 'rate': '99', 'tax': '99999'}], 3)['withheld'], '2000.00')
        for bad in ({**row(), 'month': 6}, {**row(), 'atc': 'WC999'}, {**row(), 'base': 'NaN'}):
            with self.assertRaises(ValidationError):
                calculate([bad], 3)

    def test_rounding_and_over_remittance(self):
        result = calculate([{**row(), 'base': '0.25'}, {**row(), 'base': '0.25'}], 3, '1', '0')
        self.assertEqual(result['withheld'], '0.02')
        self.assertEqual(result['due'], '-0.98')


class WorksheetTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('quarterly_admin')
        self.profile = make_profile(self.admin, key='cor_1601eq')
        self.url = reverse('workorders:quarterly-worksheet', args=[self.profile.client_id, self.profile.pk])
        self.client.force_login(self.admin)

    def preview(self):
        data = {'action': 'preview', 'year': '2026', 'quarter': '3', 'version': '0',
                'first_remittance': '0', 'second_remittance': '0',
                'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '0'}
        data.update({f'rows-0-{k}': str(v) for k, v in row().items()})
        return self.client.post(self.url, data)

    def test_direct_save_validates_and_preserves_stale_guard(self):
        data = {'action': 'save-draft', 'year': '2026', 'quarter': '3', 'version': '0',
                'first_remittance': '0', 'second_remittance': '0',
                'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '0'}
        data.update({f'rows-0-{k}': str(v) for k, v in row().items()})
        self.assertEqual(self.client.post(self.url, {**data, 'rows-0-base': 'bad'}).status_code, 409)
        self.assertFalse(QuarterlyWithholdingDraft.objects.exists())
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        draft = QuarterlyWithholdingDraft.objects.get()
        self.assertEqual(draft.data['withheld'], '2000.00')
        self.assertEqual(draft.revisions.count(), 1)
        self.assertFalse(WorkOrder.objects.exists())
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        page = self.client.get(self.url, {'year': 2026, 'quarter': 3})
        self.assertContains(page, 'Save draft')
        self.assertNotContains(page, 'Save reviewed draft')

    def test_review_save_replay_and_no_work_order(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2,000.00')
        data = {'action': 'save', 'year': '2026', 'quarter': '3', 'reviewed': 'on', 'token': response.context['token']}
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        draft = QuarterlyWithholdingDraft.objects.get()
        self.assertEqual(draft.revisions.count(), 1)
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertContains(self.client.get(self.url + '?year=2026&quarter=3'), 'TEST SUPPLIER')

    def test_signed_review_tampering_and_permission(self):
        response = self.preview()
        data = {'action': 'save', 'year': '2026', 'quarter': '3', 'reviewed': 'on', 'token': response.context['token'] + 'bad'}
        self.assertEqual(self.client.post(self.url, data).status_code, 400)
        self.assertFalse(QuarterlyWithholdingDraft.objects.exists())
        viewer = get_user_model().objects.create_user('viewer')
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_monthly_load_prefills_editable_suggestions_without_saving(self):
        ExpandedWithholdingDraft.objects.create(client=self.profile.client, year=2026, month=7, rows=[row()], total='2000')
        response = self.client.post(self.url, {'action': 'load-months', 'year': '2026', 'quarter': '3'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['amounts'].initial['first_remittance'], '2000.00')
        self.assertFalse(QuarterlyWithholdingDraft.objects.exists())

    def test_prefill_scope_and_saved_overrides(self):
        ExpandedWithholdingDraft.objects.create(client=self.profile.client, year=2026, month=7, rows=[row()], total='51174.00')
        ExpandedWithholdingDraft.objects.create(client=self.profile.client, year=2026, month=8, rows=[row()], total='30014.66')
        response = self.client.get(self.url, {'year': 2026, 'quarter': 3})
        self.assertEqual(response.context['amounts'].initial['first_remittance'], '51174.00')
        self.assertEqual(response.context['amounts'].initial['second_remittance'], '30014.66')
        response = self.client.get(self.url, {'year': 2025, 'quarter': 3})
        self.assertEqual(response.context['amounts'].initial['first_remittance'], '0.00')
        QuarterlyWithholdingDraft.objects.create(client=self.profile.client, year=2026, quarter=3,
            data={'first_remittance': '0.00', 'second_remittance': '123.45'})
        for response in [self.client.get(self.url, {'year': 2026, 'quarter': 3}),
                         self.client.post(self.url, {'action': 'load-months', 'year': 2026, 'quarter': 3})]:
            self.assertEqual(response.context['amounts'].initial['first_remittance'], '0.00')
            self.assertEqual(response.context['amounts'].initial['second_remittance'], '123.45')

    def test_penalties_calculation_validation_and_saved_draft(self):
        result = calculate([row()], 3, '500', '500', surcharge='100.25', interest='20.50', compromise='30')
        self.assertEqual(result['tax_due'], '1000.00')
        self.assertEqual(result['penalties'], '150.75')
        self.assertEqual(result['due'], '1150.75')
        for invalid in ['-1', 'NaN', '1.234']:
            with self.assertRaises(ValidationError):
                calculate([row()], 3, surcharge=invalid)
        data = {'action': 'preview', 'year': '2026', 'quarter': '3', 'version': '0',
                'first_remittance': '0', 'second_remittance': '0', 'surcharge': '100.25',
                'interest': '20.50', 'compromise': '30', 'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '0'}
        data.update({f'rows-0-{k}': str(v) for k, v in row().items()})
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(self.url, {'action': 'save', 'year': '2026', 'quarter': '3',
            'reviewed': 'on', 'token': response.context['token']})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(QuarterlyWithholdingDraft.objects.get().data['penalties'], '150.75')
