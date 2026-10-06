from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from .models import RegistrationCardScan, WorkOrder, Client
from .registration_cards import scan_company


class SavedRegistrationCardsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.actor = get_user_model().objects.create_superuser(username='cards', password='test')
        self.client.force_login(self.actor)
        self.result = {'initial': {'filings': ['1701Q']}, 'rows': [
            {'form_code': '1701Q', 'tax_type': 'Income tax', 'frequency': 'QUARTERLY', 'uncertain': False}],
            'warnings': [], 'transcript': 'test', 'model': 'test'}

    @patch('workorders.registration_cards.read_cor')
    @patch('workorders.client_directory.fetch', return_value=b'%PDF-test')
    @patch('workorders.client_directory.registration')
    def test_persistent_cards_resume_and_open_without_ai_or_directory(self, listing, fetch, reader):
        listing.return_value = {'files': [{'path': 'Office/PERMANENT/COR.pdf'}]}
        reader.return_value = self.result
        scan_company('Office')
        cache.clear()
        scan_company('Office')
        reader.assert_called_once()
        listing.assert_called_once()
        fetch.assert_called_once()
        with patch('workorders.client_directory.names', side_effect=AssertionError('No source on visit')):
            response = self.client.get(reverse('workorders:directory-client'), {'name': 'Office'})
        self.assertContains(response, 'Quarterly Income Tax Return')
        self.assertNotContains(response, 'cor-cards.js')
        self.assertNotContains(response, 'data-endpoint')
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertIn('no-store', response.headers['Cache-Control'])

    @patch('workorders.registration_cards.read_cor')
    @patch('workorders.client_directory.fetch', return_value=b'%PDF-test')
    @patch('workorders.client_directory.registration')
    def test_directory_tabs_show_unreviewed_details_without_creating_records(self, listing, fetch, reader):
        listing.return_value = {'files': [{'path': 'Office/PERMANENT/COR.pdf'}]}
        reader.return_value = self.result | {'initial': {'filings': ['1701Q'], 'registered_name': 'FAKE READ NAME',
            'tin1': '600', 'tin2': '042', 'tin3': '484', 'tin4': '00000', 'rdo_code': '053'}}
        scan_company('Office')
        url = reverse('workorders:directory-client')
        with patch('workorders.client_directory.names', return_value=['Office']):
            cards = self.client.get(url, {'name': 'Office'})
            details = self.client.get(url, {'name': 'Office', 'tab': 'details'})
            history = self.client.get(url, {'name': 'Office', 'tab': 'history'})
            unknown = self.client.get(url, {'name': 'Office', 'tab': 'nope'})
        self.assertContains(cards, 'Quarterly Income Tax Return')
        self.assertContains(details, 'FAKE READ NAME')
        self.assertContains(details, 'have not been reviewed')
        self.assertContains(history, 'No filings yet')
        self.assertContains(unknown, 'Quarterly Income Tax Return')
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(WorkOrder.objects.count(), 0)

    @patch('workorders.client_directory.registration')
    def test_error_and_empty_are_distinct_and_errors_retry(self, listing):
        listing.side_effect = RuntimeError('private upstream error')
        self.assertEqual(scan_company('Office').status, 'ERROR')
        self.assertNotIn('private', RegistrationCardScan.objects.get().message)
        listing.side_effect = None
        listing.return_value = {'files': []}
        self.assertEqual(scan_company('Office').status, 'EMPTY')

    @patch('workorders.registration_cards.read_cor')
    @patch('workorders.client_directory.fetch', return_value=b'%PDF-test')
    @patch('workorders.client_directory.registration')
    def test_refresh_reuses_digest_and_removes_deleted_documents(self, listing, fetch, reader):
        listing.return_value = {'files': [{'path': 'Office/PERMANENT/COR.pdf'}]}
        reader.return_value = self.result
        scan_company('Office')
        scan_company('Office', refresh=True)
        reader.assert_called_once()
        listing.return_value = {'files': []}
        scan = scan_company('Office', refresh=True)
        self.assertEqual(scan.documents, [])
        self.assertEqual(scan.status, 'EMPTY')
