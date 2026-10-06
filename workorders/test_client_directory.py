from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from . import client_directory as directory
from .models import Client, WorkOrder


@override_settings(CLIENT_FILES_URL='http://127.0.0.1:3021')
class ClientDirectoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.actor = get_user_model().objects.create_superuser(username='directory-admin', password='test-password')
        self.client.force_login(self.actor)

    @patch('workorders.client_directory.read_json')
    def test_directory_search_pagination_and_no_filing_records(self, api):
        api.return_value = {'clients': ['.trash', '../escape', 'bad/name'] + [f'Office {i:02}' for i in range(26)]}
        response = self.client.get(reverse('workorders:clients'))
        self.assertEqual(response.context['page_obj'].paginator.count, 26)
        self.assertEqual(len(response.context['page_obj']), 20)
        self.assertNotContains(response, '.trash')
        self.assertContains(response, 'Filing setup needed')
        response = self.client.get(reverse('workorders:clients'), {'q': 'office 25'})
        self.assertContains(response, 'Office 25')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertEqual(api.call_count, 1)

    @patch('workorders.client_directory.names', side_effect=directory.DirectoryUnavailable('Directory unavailable'))
    def test_outage_keeps_list_accessible(self, names):
        response = self.client.get(reverse('workorders:clients'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Configured filing clients are still available')

    @patch('workorders.client_directory.read_json')
    def test_registration_filters_paths_and_escapes_names(self, api):
        name = 'A & B'
        api.side_effect = [{'clients': [name]}, {'hasPermanent': True, 'files': [
            {'path': 'A & B/PERMANENT/<COR>.pdf'}, {'path': 'Other/PERMANENT/COR.pdf'},
            {'path': 'A & B/PERMANENT/../secret'}, {'path': 'A & B/PERMANENT/C:/secret'}]}]
        result = directory.registration(name)
        self.assertEqual(result['files'][0]['name'], '<COR>.pdf')
        self.assertEqual(len(result['files']), 1)

    @patch('workorders.client_directory.names', return_value=['Office'])
    @patch('workorders.client_directory.read_json')
    def test_registration_excludes_payment_and_supporting_documents(self, api, names):
        filenames = ['BIR FORM 0605 - LOSS COR PROOF OF PAYMENT.pdf',
                     'COR payment receipt.pdf', 'Affidavit of loss COR.pdf',
                     'Application for COR.pdf', 'records.pdf', 'COR.docx',
                     'BIR 2303 - COR - Branch 1.pdf', 'Amended_COR.pdf',
                     'Certificate of Registration.pdf']
        api.return_value = {'hasPermanent': True, 'files': [
            {'path': 'Office/PERMANENT/COR/' + name} for name in filenames]}
        files = directory.registration('Office')['files']
        self.assertEqual([item['name'] for item in files], filenames[-3:])

    @patch('workorders.client_directory.names', return_value=['Office'])
    def test_unknown_directory_is_not_found(self, names):
        self.assertEqual(self.client.get(reverse('workorders:directory-client'), {'name': '../other'}).status_code, 404)

    @patch('workorders.client_directory.fetch')
    @patch('workorders.client_directory.registration')
    def test_document_requires_signed_actor_and_current_registration(self, registration, fetch):
        item = {'name': 'COR.pdf', 'path': 'Office/PERMANENT/COR.pdf'}
        registration.return_value = {'files': [item]}
        fetch.return_value = b'%PDF-1.7\nexample'
        token = signing.dumps({'actor': self.actor.pk, 'client': 'Office', 'path': item['path']}, salt='registration-file')
        url = reverse('workorders:registration-file')
        response = self.client.get(url, {'token': token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.get(url, {'token': token + 'tampered'}).status_code, 404)
        other = get_user_model().objects.create_superuser(username='other-admin')
        self.client.force_login(other)
        self.assertEqual(self.client.get(url, {'token': token}).status_code, 404)
        self.client.force_login(self.actor)
        registration.return_value = {'files': []}
        self.assertEqual(self.client.get(url, {'token': token}).status_code, 404)
        self.assertEqual(fetch.call_count, 1)

    @patch('workorders.client_directory.names')
    def test_permission_checked_before_source_access(self, names):
        user = get_user_model().objects.create_user(username='no-access')
        self.client.force_login(user)
        for route in ['clients', 'directory-client', 'registration-file']:
            self.assertEqual(self.client.get(reverse('workorders:' + route)).status_code, 403)
        names.assert_not_called()

    @override_settings(CLIENT_FILES_URL='http://example.com')
    def test_nonlocal_source_rejected(self):
        with self.assertRaises(directory.DirectoryUnavailable):
            directory.fetch('/api/clients')
