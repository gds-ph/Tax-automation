from copy import deepcopy
from types import SimpleNamespace
from django.test import SimpleTestCase
from .cor_selection import select_documents


def doc(key, date='March 24, 2025', score=50, branch='00000'):
    return {'sha256': key, 'path': key, 'result': {'initial': {
        'tin1': '123', 'tin2': '456', 'tin3': '789', 'tin4': branch,
        'registered_name': 'Test Inc', 'rdo_code': '044', 'registered_address': 'Test address'},
        'rows': [{'form_code': '2551Q', 'uncertain': False}],
        'readability_score': score, 'transcript': f'OCN: ABC123\nDate OCN Generated: {date}'}}


class CORSelectionTests(SimpleTestCase):
    def select(self, docs, preferred=''):
        return select_documents(SimpleNamespace(documents=docs, preferred_sha256=preferred, selection_note='Manual review'))[0]

    def test_latest_per_company_then_clearest(self):
        docs = [doc('old', 'January 5, 2023', 100), doc('blur', score=20), doc('clear', score=90), doc('branch', branch='00001')]
        self.assertEqual([d['sha256'] for d in self.select(docs)], ['clear'])
        self.assertEqual(len(docs), 4)

    def test_same_date_selects_one_copy(self):
        one, two = doc('one'), doc('two')
        two['result']['rows'][0]['form_code'] = '2550Q'
        self.assertEqual(len(self.select([one, two])), 1)

    def test_missing_date_does_not_use_registration_date(self):
        one, two = doc('one'), doc('two')
        two['result']['transcript'] = 'Registration Date: March 24, 2026'
        self.assertEqual(len(self.select([one, two])), 1)

    def test_conflicting_page_dates_excluded_from_date_comparison(self):
        one, two = doc('one'), doc('two')
        two['result']['transcript'] += '\nDate OCN Generated: March 25, 2025'
        self.assertEqual(len(self.select([one, two])), 1)

    def test_identity_and_manual_preference(self):
        one, two = doc('one'), doc('two')
        two['result']['initial']['tin2'] = '999'
        self.assertEqual(len(self.select([one, two])), 1)
        self.assertEqual(self.select([one, two], 'one'), [one])

    def test_manual_preference_cannot_override_newer_certificate(self):
        old, new = doc('old', 'January 1, 2020'), doc('new')
        self.assertEqual(self.select([old, new], 'old'), [new])

    def test_all_undated_requires_review(self):
        docs = [doc('one', 'unknown'), doc('two', 'unknown')]
        self.assertEqual(self.select(docs), docs)
