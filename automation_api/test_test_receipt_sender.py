from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, override_settings
from .receipts import lookup
from .gmail_receipts import lookup_receipt
from workorders.contact_defaults import TEST_CLIENT_CODES

class TestReceiptSenderTests(SimpleTestCase):
    @patch('automation_api.receipts.lookup_receipt')
    def test_exception_scoped_to_three_clients(self, find):
        for code in (*TEST_CLIENT_CODES, 'REAL-CLIENT'):
            find.reset_mock()
            find.side_effect=[{'found':False},{'found':True}]
            check=SimpleNamespace(filename='test.xml', submitted_after='date', approval=SimpleNamespace(
                work_order=SimpleNamespace(legacy_client_reference=code,client_id=None)))
            result=lookup(check)
            if code in TEST_CLIENT_CODES:
                self.assertTrue(result['test_receipt'])
                self.assertEqual(find.call_args.kwargs, {'sender':'heiner@gds.ph'})
            else:
                self.assertEqual(find.call_count,1)
                self.assertFalse(result['found'])

    @override_settings(GMAIL_ADDRESS='test@example.invalid',GMAIL_APP_PASSWORD='test-only',GMAIL_RECEIPT_SENDER='ebirforms-noreply@bir.gov.ph')
    @patch('automation_api.gmail_receipts.GmailMailbox.current',return_value=None)
    @patch('automation_api.gmail_receipts.imaplib.IMAP4_SSL')
    def test_imap_sender_filename_subject_and_date(self, imap, mailbox):
        name='63984860500000-1600VTv2018-082026.xml'
        since=datetime(2026,10,4,12,tzinfo=timezone.utc)
        for sender,filename,subject,date,expected in [
            ('Heiner <heiner@gds.ph>',name,'Tax Return Receipt Confirmation','Sun, 04 Oct 2026 13:00:00 +0000',True),
            ('heiner@gds.ph.evil.example',name,'Tax Return Receipt Confirmation','Sun, 04 Oct 2026 13:00:00 +0000',False),
            ('heiner@gds.ph','other.xml','Tax Return Receipt Confirmation','Sun, 04 Oct 2026 13:00:00 +0000',False),
            ('heiner@gds.ph',name,'Other','Sun, 04 Oct 2026 13:00:00 +0000',False),
            ('heiner@gds.ph',name,'Tax Return Receipt Confirmation','Sun, 04 Oct 2026 11:00:00 +0000',False)]:
            msg=EmailMessage();msg['From']=sender;msg['Subject']=subject;msg['Date']=date
            msg.set_content('File name: '+filename)
            imap.return_value.search.return_value=('OK',[b'1'])
            imap.return_value.fetch.return_value=('OK',[(b'1',msg.as_bytes())])
            self.assertEqual(lookup_receipt(name,since,sender='heiner@gds.ph')['found'],expected)
        self.assertFalse(lookup_receipt(name,since)['found'])
