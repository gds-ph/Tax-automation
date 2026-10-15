from decimal import Decimal
from django.test import SimpleTestCase
from .atc_catalog import ATC_ENTRIES, ATC_BY_CODE
from .withholding_views import RowForm


class AtcLookupTests(SimpleTestCase):
    def form(self, **changes):
        data = dict(payee='Supplier', tin='001-002-003-00000', atc='WC120', base='100000', rate='2')
        data.update(changes)
        return RowForm(data)

    def test_lookup_populates_missing_readonly_rate(self):
        form = self.form(atc='wc158', rate='')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['rate'], Decimal('1'))
        self.assertEqual(form.cleaned_data['atc'], 'WC158')

    def test_tampered_rate_rejected(self):
        form = self.form(rate='1')
        self.assertFalse(form.is_valid())
        self.assertIn('rate', form.errors)

    def test_unknown_or_final_tax_code_rejected(self):
        for code in ('WC999', 'WC810', 'WI240'):
            form = self.form(atc=code)
            self.assertFalse(form.is_valid())
            self.assertIn('atc', form.errors)

    def test_catalog_rates_and_uniqueness(self):
        self.assertEqual(len(ATC_ENTRIES), len(ATC_BY_CODE))
        for code, rate in {'WC120':'2', 'WC158':'1', 'WI661':'15', 'WC661':'15', 'WC651':'15', 'WC710':'15', 'WC840':'0.5', 'WC850':'0.5', 'WC860':'0.5'}.items():
            self.assertEqual(ATC_BY_CODE[code]['rate'], rate)

    def test_fractional_rate(self):
        form = self.form(atc='WC840', rate='0.5')
        self.assertTrue(form.is_valid(), form.errors)
