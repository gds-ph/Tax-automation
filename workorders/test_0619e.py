from io import BytesIO
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from openpyxl import Workbook

from .expanded_withholding import normalize_rows, total, import_sheet
from .models import ExpandedWithholdingDraft, ExpandedWithholdingRevision, WorkOrder
from .test_support import make_profile


def sample(**changes):
    row = dict(payee='FAKE SUPPLIER', tin='001-002-003-000', atc='WC120', base='1242354.00', rate='2', reference='TEST ONLY')
    row.update(changes)
    return row


def workbook(rows=None):
    book = Workbook();sheet = book.active;sheet.title = 'Transactions'
    sheet.append(['Payee', 'TIN', 'ATC Code', 'Tax Base', 'Tax Rate', 'Withholding Tax', 'Particulars', 'Year', 'Month'])
    for row in rows or [['FAKE SUPPLIER', '001-002-003-000', 'WC120', 1242354, .02, 24847.08, 'TEST', 2026, 7]]:
        sheet.append(row)
    output = BytesIO();book.save(output)
    return SimpleUploadedFile('test.xlsx', output.getvalue())


class ArithmeticTests(SimpleTestCase):
    def test_sample_totals(self):
        july = normalize_rows([sample(), sample(base='1316346')])
        august = normalize_rows([sample(base='51964', atc='WC158', rate='1'), sample(base='1474751')])
        self.assertEqual(total(july), Decimal('51174.00'))
        self.assertEqual(total(august), Decimal('30014.66'))

    def test_decimal_rounding(self):
        self.assertEqual(normalize_rows([sample(base='1.25', rate='2')])[0]['tax'], '0.03')

    def test_invalid_values_and_mismatch(self):
        for changes in ({'base':'NaN'}, {'base':'-1'}, {'rate':'101'}, {'rate':'0'}, {'tin':'123'}, {'tax':'1'}, {'base':'0.001'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                normalize_rows([sample(**changes)])

    def test_import_and_period_check(self):
        self.assertEqual(total(import_sheet(workbook(), 'Transactions', 2026, 7)), Decimal('24847.08'))
        with self.assertRaises(ValidationError):
            import_sheet(workbook(), 'Transactions', 2026, 8)

    def test_missing_formula_cache_rejected(self):
        with self.assertRaises(ValidationError):
            import_sheet(workbook([['FAKE', '001-002-003-000', 'WC120', '=F2/E2', .02, 2, '']]), 'Transactions', 2026, 7)

    def test_multiple_schedules_rejected(self):
        rows = [['Payee', 'TIN', 'ATC Code', 'Tax Base', 'Tax Rate', 'Withholding Tax', 'Particulars']]
        with self.assertRaises(ValidationError):
            import_sheet(workbook(rows), 'Transactions', 2026, 7)


class DraftTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('preparer', password='test-only')
        self.taxpayer = make_profile(self.user).client
        self.url = reverse('workorders:withholding-draft', args=[self.taxpayer.pk])
        self.client.force_login(self.user)

    def preview(self):
        return self.client.post(self.url, {'action':'import', 'year':2026, 'month':7, 'sheet':'Transactions', 'workbook':workbook()})

    def save(self, token):
        return self.client.post(self.url, {'action':'save', 'year':2026, 'month':7, 'reviewed':'on', 'preview_token':token})

    def test_preview_save_and_replay_protection(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '24,847.08')
        self.assertFalse(ExpandedWithholdingDraft.objects.exists())
        token = response.context['preview_token']
        self.assertEqual(self.save(token).status_code, 302)
        self.assertEqual(ExpandedWithholdingRevision.objects.count(), 1)
        self.assertEqual(self.save(token).status_code, 400)
        self.assertEqual(ExpandedWithholdingRevision.objects.count(), 1)
        self.assertFalse(WorkOrder.objects.exists())
        page = self.client.get(self.url, {'year':2026, 'month':7})
        self.assertEqual(page.status_code, 200)

    def test_tampered_preview_rejected(self):
        self.assertEqual(self.save('invalid').status_code, 400)
        self.assertFalse(ExpandedWithholdingDraft.objects.exists())

    def test_third_month_rejected(self):
        response = self.client.post(self.url, {'year':2026, 'month':9, 'action':'import', 'workbook':workbook()})
        self.assertEqual(response.status_code, 400)

    def test_permissions(self):
        viewer = get_user_model().objects.create_user('viewer', password='test-only')
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.preview().status_code, 403)

    def test_revision_keeps_original(self):
        self.save(self.preview().context['preview_token'])
        self.save(self.preview().context['preview_token'])
        self.assertEqual(list(ExpandedWithholdingRevision.objects.values_list('version', flat=True)), [1, 2])
        self.assertEqual(ExpandedWithholdingDraft.objects.get().version, 2)
