import base64
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .gmail_receipts import lookup_receipt, receipt_text


class HtmlReceiptTests(SimpleTestCase):
    def test_visible_html_and_plain_precedence(self):
        self.assertEqual(receipt_text('', '<p>File&nbsp;name: <b>return.xml</b></p>').strip(),
                         'File\xa0name: return.xml')
        self.assertEqual(receipt_text('plain', '<p>other</p>'), 'plain')

    @override_settings(GMAIL_ADDRESS='', GMAIL_APP_PASSWORD='',
                       GMAIL_RECEIPT_SENDER='ebirforms-noreply@bir.gov.ph')
    @patch('automation_api.gmail_receipts.GmailMailbox.current', return_value=None)
    @patch('automation_api.gmail_receipts._get')
    def test_html_receipt_retains_filename_subject_and_time_checks(self, get, mailbox):
        name = '69696569000000-1601Cv2018-092026.xml'
        since = datetime(2026, 9, 28, 8, 33, tzinfo=timezone.utc)
        for filename, subject, timestamp, expected in (
            (name, 'Tax Return Receipt Confirmation', since.timestamp() + 360, True),
            ('other.xml', 'Tax Return Receipt Confirmation', since.timestamp() + 360, False),
            (name, 'Unrelated message', since.timestamp() + 360, False),
            (name, 'Tax Return Receipt Confirmation', since.timestamp() - 360, False),
        ):
            with self.subTest(filename=filename, subject=subject, timestamp=timestamp):
                message = {'id': 'receipt', 'internalDate': str(int(timestamp * 1000)),
                           'payload': {'mimeType': 'text/html', 'headers': [
                               {'name': 'From', 'value': 'ebirforms-noreply@bir.gov.ph'},
                               {'name': 'Subject', 'value': subject}],
                               'body': {'data': base64.urlsafe_b64encode(
                                   f'<p>File name: <b>{filename}</b><br>Date received by BIR: 28 September 2026</p>'.encode()).decode()}}}
                get.side_effect = lambda path, params: message if path.startswith('/messages/') else {'messages': [{'id': 'receipt'}]}
                self.assertEqual(lookup_receipt(name, since)['found'], expected)
