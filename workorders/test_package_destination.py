from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from .client_directory import archive_final_package, DirectoryUnavailable, month_folder_name

class PackageDestinationTests(SimpleTestCase):
    def test_month_folder_names_match_office_format(self):
        expected = ['01 JANUARY', '02 FEBRUARY', '03 MARCH', '04 APRIL',
                    '05 MAY', '06 JUNE', '07 JULY', '08 AUGUST', '09 SEPTEMBER',
                    '10 OCTOBER', '11 NOVEMBER', '12 DECEMBER']
        self.assertEqual([month_folder_name(month) for month in range(1, 13)], expected)
        for invalid in (0, 13, None, True, '../January'):
            with self.assertRaises(DirectoryUnavailable):
                month_folder_name(invalid)

    @patch('workorders.client_directory.upload_pdf', return_value={'saved': [{'name': 'complete.pdf'}]})
    @patch('workorders.client_directory.read_json')
    def test_existing_folder_priority_and_legacy_paths(self, browse, upload):
        for names, expected in [(['BIR', 'FILED RETURNS'], 'BIR'), (['FILED RETURNS'], 'FILED RETURNS'), (['BIR FILING'], 'BIR FILING'), (['bir'], 'bir')]:
            browse.return_value = {'entries': [{'name': n, 'type': 'folder'} for n in names]}
            for path in ['Company', 'Company/BIR', 'Company/BIR FILING', 'Company/FILED RETURNS', 'Company/PERMANENT/BIR',
                         '//192.168.8.251/Starlight/Starlight offline/CLIENT/Company/PERMANENT/BIR']:
                result = archive_final_package(SimpleNamespace(client_folder_path=path), None, 'complete.pdf', b'pdf')
                self.assertEqual(result['path'], 'Company/' + expected)
                browse.assert_called_with('/api/browse', {'path': 'Company'})
                upload.assert_called_with('Company/' + expected, 'complete.pdf', b'pdf')

    @patch('workorders.client_directory.upload_pdf')
    @patch('workorders.client_directory.read_json')
    def test_missing_folders_or_service_failure_prevents_upload(self, browse, upload):
        for entries in [[], [{'name': 'BIR', 'type': 'file'}], [{'name': '../BIR', 'type': 'folder'}]]:
            browse.return_value = {'entries': entries}
            with self.assertRaises(DirectoryUnavailable):
                archive_final_package(SimpleNamespace(client_folder_path='Company'), None, 'complete.pdf', b'pdf')
        browse.side_effect = DirectoryUnavailable('Unavailable')
        with self.assertRaises(DirectoryUnavailable):
            archive_final_package(SimpleNamespace(client_folder_path='Company'), None, 'complete.pdf', b'pdf')
        upload.assert_not_called()

    @patch('workorders.client_directory.create_folder', return_value={'exists': True})
    @patch('workorders.client_directory.upload_pdf', return_value={'saved': [{'name': 'complete.pdf'}]})
    @patch('workorders.client_directory.read_json')
    def test_monthly_packages_use_filing_year_and_numbered_month(self, browse, upload, folder):
        from unittest.mock import call
        for destination in ('BIR', 'BIR FILING', 'FILED RETURNS'):
            with self.subTest(destination=destination):
                folder.reset_mock()
                browse.return_value = {'entries': [{'name': destination, 'type': 'folder'}]}
                order = SimpleNamespace(filing_month=1, filing_year='2025')
                result = archive_final_package(SimpleNamespace(client_folder_path='Company'), order, 'complete.pdf', b'pdf')
                base = 'Company/' + destination
                self.assertEqual(folder.call_args_list, [call(base, '2025'), call(base + '/2025', '01 JANUARY')])
                self.assertEqual(result['path'], base + '/2025/01 JANUARY')
                upload.assert_called_with(result['path'], 'complete.pdf', b'pdf')

    @patch('workorders.client_directory.create_folder', side_effect=DirectoryUnavailable('Cannot create folder'))
    @patch('workorders.client_directory.upload_pdf')
    @patch('workorders.client_directory.read_json', return_value={'entries': [{'name': 'BIR', 'type': 'folder'}]})
    def test_folder_failure_does_not_upload_to_wrong_location(self, browse, upload, folder):
        with self.assertRaises(DirectoryUnavailable):
            archive_final_package(SimpleNamespace(client_folder_path='Company'),
                SimpleNamespace(filing_month=12, filing_year='2026'), 'complete.pdf', b'pdf')
        upload.assert_not_called()
