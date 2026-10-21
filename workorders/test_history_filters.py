from types import SimpleNamespace
from django.test import SimpleTestCase
from .history_filters import history_context

class Rows(list):
    def order_by(self, *args): return self

class HistoryFilterTests(SimpleTestCase):
    def setUp(self):
        self.rows=Rows([SimpleNamespace(form_code='1601C',operational_status='Awaiting submission approval',filing_year='2026',filing_month=9,filing_quarter=None) for _ in range(30)])
        self.rows.append(SimpleNamespace(form_code='1601EQ',operational_status='System failure',filing_year='2025',filing_month=None,filing_quarter=3))
    def test_combined_filters_and_period(self):
        c=history_context(self.rows,{'history_form':'1601EQ','history_status':'System failure','history_year':'2025','history_period':'Q3'})
        self.assertEqual(c['history_count'],1)
        self.assertEqual(c['orders'][0].form_code,'1601EQ')
    def test_pagination_preserves_filter(self):
        c=history_context(self.rows,{'history_form':'1601C','page':'2'})
        self.assertEqual(len(c['orders']),5)
        self.assertIn('history_form=1601C',c['history_query'])
    def test_no_matches_and_permission_empty_queryset(self):
        self.assertEqual(history_context(self.rows,{'history_year':'1999'})['history_count'],0)
        self.assertEqual(history_context(Rows(),{})['history_count'],0)
