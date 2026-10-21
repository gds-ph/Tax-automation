from types import SimpleNamespace
from unittest.mock import patch, call
from django.test import SimpleTestCase
from . import client_directory as d

class ArchivePeriodTests(SimpleTestCase):
    @patch('workorders.client_directory.create_folder')
    @patch('workorders.client_directory.read_json')
    def test_all_months_and_quarters_share_period_folders(self, browse, create):
        browse.return_value = {'entries': [{'name': 'BIR FILING', 'type': 'folder'}]}
        client = SimpleNamespace(client_folder_path='Company')
        for month, quarter, expected in [(9,None,9),(None,1,3),(None,2,6),(None,3,9),(None,4,12)]:
            with self.subTest(month=month, quarter=quarter):
                order=SimpleNamespace(filing_month=month, filing_quarter=quarter, filing_year='2026', year_end_month='12')
                self.assertEqual(d.filing_folder(client,order), 'Company/BIR FILING/2026/' + d.month_folder_name(expected))
                create.assert_has_calls([call('Company/BIR FILING','2026'),call('Company/BIR FILING/2026',d.month_folder_name(expected))])
                create.reset_mock()

    @patch('workorders.client_directory.create_folder')
    @patch('workorders.client_directory.read_json')
    def test_unsupported_period_does_not_create_wrong_folder(self,browse,create):
        browse.return_value={'entries':[{'name':'BIR','type':'folder'}]}
        for quarter, end in [(None,'12'),(5,'12'),(1,'06')]:
            with self.assertRaises(d.DirectoryUnavailable):
                d.filing_folder(SimpleNamespace(client_folder_path='Company'),SimpleNamespace(filing_month=None,filing_quarter=quarter,filing_year='2026',year_end_month=end))
        create.assert_not_called()
