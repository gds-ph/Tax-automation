import email
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, override_settings
from .gmail_receipts import _lookup_imap

@override_settings(GMAIL_ADDRESS='test@example.com', GMAIL_APP_PASSWORD='test', GMAIL_RECEIPT_SENDER='ebirforms-noreply@bir.gov.ph')
class ImapReceiptTests(SimpleTestCase):
    @patch('automation_api.gmail_receipts.GmailMailbox.current', return_value=None)
    @patch('automation_api.gmail_receipts.imaplib.IMAP4_SSL')
    def test_exact_receipt_and_rejected_evidence(self, connect, config):
        name='01095303200000-2550Qv2024-122026Q3.xml'
        since=datetime(2026,10,14,8,34,tzinfo=timezone.utc)
        for filename,sender,subject,date,expected in (
            (name,'ebirforms-noreply@bir.gov.ph','Tax Return Receipt Confirmation','Wed, 14 Oct 2026 09:00:00 +0000',True),
            ('other.xml','ebirforms-noreply@bir.gov.ph','Tax Return Receipt Confirmation','Wed, 14 Oct 2026 09:00:00 +0000',False),
            (name,'other@example.com','Tax Return Receipt Confirmation','Wed, 14 Oct 2026 09:00:00 +0000',False),
            (name,'ebirforms-noreply@bir.gov.ph','Other subject','Wed, 14 Oct 2026 09:00:00 +0000',False),
            (name,'ebirforms-noreply@bir.gov.ph','Tax Return Receipt Confirmation','Wed, 14 Oct 2026 08:00:00 +0000',False),
        ):
            with self.subTest(filename=filename,sender=sender,subject=subject,date=date):
                mailbox=MagicMock();connect.return_value=mailbox
                mailbox.select.return_value=('OK',[b'1'])
                mailbox.search.return_value=('OK',[b'1'])
                message=email.message.EmailMessage()
                message['From']=sender;message['Subject']=subject;message['Date']=date;message['Message-ID']='<receipt>'
                message.set_content(f'File name: {filename}')
                mailbox.fetch.return_value=('OK',[(b'1',message.as_bytes())])
                self.assertEqual(_lookup_imap(name,since)['found'],expected)
                connect.assert_called_with('imap.gmail.com',993,timeout=30)
                self.assertIn('TEXT',mailbox.search.call_args.args)
                self.assertIn('"'+name+'"',mailbox.search.call_args.args)
                mailbox.fetch.assert_called_with(b'1','(BODY.PEEK[] INTERNALDATE)')
                mailbox.logout.assert_called_once()

    @patch('automation_api.gmail_receipts.GmailMailbox.current', return_value=None)
    @patch('automation_api.gmail_receipts.imaplib.IMAP4_SSL')
    def test_timeout_exits_and_closes_connection(self,connect,config):
        mailbox=connect.return_value
        mailbox.select.return_value=('OK',[])
        mailbox.search.side_effect=TimeoutError('network timeout')
        with self.assertRaises(TimeoutError):
            _lookup_imap('01095303200000-2550Qv2024-122026Q3.xml',datetime.now(timezone.utc))
        mailbox.logout.assert_called_once()
