import subprocess
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import BirReceiptCheck, Stage2Approval
from .receipts import poll_receipts, escalate_overdue_trrc
from .stage2 import approve
from .test_worker_api import WorkerApiTests
from workorders.models import WorkOrder


class ReceiptTests(WorkerApiTests):

    @override_settings(GMAIL_ADDRESS='sender@example.com', GMAIL_APP_PASSWORD='test-password',
                        TRRC_ESCALATION_RECIPIENT='heiner@gds.ph')
    @patch('automation_api.receipts.smtplib.SMTP_SSL')
    @patch('automation_api.receipts.lookup', return_value={'found': False})
    def test_overdue_1601c_sends_one_simulation_escalation(self, lookup, smtp):
        order, approval = self.pending()
        order.expected_form_number = '1601Cv2018'
        order.form_code = '1601C'
        order.save(_service_write=True, update_fields=['expected_form_number', 'form_code'])
        poll_receipts()
        check = BirReceiptCheck.objects.get()
        check.submitted_after = timezone.now() - timedelta(days=8)
        check.next_check_at = timezone.now() + timedelta(days=1)
        check.save(update_fields=['submitted_after', 'next_check_at'])
        self.assertEqual(escalate_overdue_trrc(), (1, 0))
        check.refresh_from_db()
        self.assertEqual(check.trrc_escalation_recipient, 'heiner@gds.ph')
        self.assertIsNotNone(check.trrc_escalation_sent_at)
        msg = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(msg['To'], 'heiner@gds.ph')
        self.assertIn('NO TRRC RECEIVED FOR FORM 1601C', msg['Subject'])
        self.assertIn(order.combined_tin[:3] + '-' + order.combined_tin[3:6] + '-' + order.combined_tin[6:9] + '-' + order.combined_tin[9:], msg.get_content())
        self.assertEqual(escalate_overdue_trrc(), (0, 0))

    @override_settings(GMAIL_ADDRESS='sender@example.com', GMAIL_APP_PASSWORD='test-password',
                        TRRC_ESCALATION_RECIPIENT='heiner@gds.ph')
    @patch('automation_api.receipts.smtplib.SMTP_SSL')
    @patch('automation_api.receipts.lookup', return_value={'found': False})
    def test_saved_rdo_recipient_overrides_server_setting(self, lookup, smtp):
        from audit.models import SystemSetting
        SystemSetting.objects.create(key='trrc_escalation_recipient', value='rdo@example.com')
        order, approval = self.pending()
        order.expected_form_number = '1601Cv2018'
        order.form_code = '1601C'
        order.save(_service_write=True, update_fields=['expected_form_number', 'form_code'])
        poll_receipts()
        check = BirReceiptCheck.objects.get()
        check.submitted_after = timezone.now() - timedelta(days=8)
        check.next_check_at = timezone.now() + timedelta(days=1)
        check.save(update_fields=['submitted_after', 'next_check_at'])
        self.assertEqual(escalate_overdue_trrc(), (1, 0))
        check.refresh_from_db()
        self.assertEqual(check.trrc_escalation_recipient, 'rdo@example.com')
        self.assertIsNotNone(check.trrc_escalation_sent_at)
        msg = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(msg['To'], 'rdo@example.com')
        self.assertIn('NO TRRC RECEIVED FOR FORM 1601C', msg['Subject'])
        self.assertIn(order.combined_tin[:3] + '-' + order.combined_tin[3:6] + '-' + order.combined_tin[6:9] + '-' + order.combined_tin[9:], msg.get_content())
        self.assertEqual(escalate_overdue_trrc(), (0, 0))

    @patch('automation_api.receipts.lookup', return_value={'found': False})
    def test_configured_email_interval_schedules_next_check(self, lookup):
        from audit.models import SystemSetting
        SystemSetting.objects.create(key='receipt_check_interval_minutes', value='5')
        self.pending()
        poll_receipts()
        check = BirReceiptCheck.objects.get()
        self.assertEqual(check.next_check_at - check.last_checked_at, timedelta(minutes=5))

    @override_settings(TRRC_ESCALATION_AFTER_MINUTES=0, TRRC_ESCALATION_AFTER_DAYS=7)
    @patch('automation_api.receipts.send_trrc_escalation', return_value='rdo@example.com')
    def test_all_tracked_forms_escalate_only_when_overdue_and_without_receipt(self, send):
        order, approval = self.pending()
        check = BirReceiptCheck.objects.create(approval=approval, filename='test.xml',
            submitted_after=timezone.now() - timedelta(days=6))
        for code in ['1601C', '1601EQ', '2551Q', '1702Q']:
            with self.subTest(form=code):
                order.form_code = code
                order.expected_form_number = code
                order.save(_service_write=True, update_fields=['form_code', 'expected_form_number'])
                check.trrc_escalation_sent_at = None
                check.received_at = None
                check.submitted_after = timezone.now() - timedelta(days=6)
                check.save()
                self.assertEqual(escalate_overdue_trrc(), (0, 0))
                check.submitted_after = timezone.now() - timedelta(days=8)
                check.received_at = timezone.now()
                check.save()
                self.assertEqual(escalate_overdue_trrc(), (0, 0))
                check.received_at = None
                check.save()
                self.assertEqual(escalate_overdue_trrc(), (1, 0))
                self.assertEqual(escalate_overdue_trrc(), (0, 0))
        self.assertEqual(send.call_count, 4)

    @override_settings(GMAIL_ADDRESS='sender@example.com', GMAIL_APP_PASSWORD='test-password')
    @patch('automation_api.receipts.smtplib.SMTP_SSL')
    def test_all_three_test_clients_override_rdo_recipient(self, smtp):
        from workorders.contact_defaults import TEST_CLIENT_CODES
        from audit.models import SystemSetting
        from .receipts import send_trrc_escalation, discover_pending
        SystemSetting.objects.create(key='trrc_escalation_recipient', value='rdo@example.com')
        order, approval = self.pending()
        discover_pending()
        for code in TEST_CLIENT_CODES:
            order.legacy_client_reference = code
            order.save(_service_write=True, update_fields=['legacy_client_reference'])
            check = BirReceiptCheck.objects.get(approval=approval)
            self.assertEqual(send_trrc_escalation(check), 'heiner@gds.ph')
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'heiner@gds.ph')
            self.assertIsNone(message['Cc'])
            self.assertIsNone(message['Bcc'])

    @patch('automation_api.receipts.finalize')
    @patch('automation_api.receipts.lookup')
    @patch('automation_api.receipts.send_trrc_escalation')
    def test_test_client_receipt_triggers_finalize_without_followup(self, send, lookup, finalize):
        order, approval = self.pending()
        order.legacy_client_reference = 'DUMMY-CLIENT-001'
        order.save(_service_write=True, update_fields=['legacy_client_reference'])
        approval.success_screenshot = 'test-only.png'
        approval.save(_service_write=True)
        lookup.return_value = {'found':True, 'filename':order.saved_xml_path.split('\\')[-1],
            'message':{'id':'test-trrc', 'date':timezone.now().isoformat(), 'text':'receipt'}}
        self.assertEqual(poll_receipts(), (1, 1, 0))
        finalize.assert_called_once()
        send.assert_not_called()
        self.assertIsNotNone(BirReceiptCheck.objects.get().received_at)

    def pending(self, state='SUBMITTED_WAITING_FOR_CONFIRMATION'):
        job = self.job()
        self.upload(job)
        self.result(job)
        order = WorkOrder.objects.get()
        approval = approve(actor=self.actor, order_id=order.pk, version=order.version,
            digest=order.prepared_pdf_sha256, submission_enabled=True)
        order.saved_xml_path = r'C:\eBIRForms\savefile\68070737500000-1702Qv2018C-2026Q2V0.xml'
        order.save(_service_write=True)
        approval.submission_enabled = True
        approval.state = state
        approval.save(_service_write=True)
        return order, approval

    @patch('automation_api.receipts.lookup')
    def test_only_submitted_filings_are_polled(self, lookup):
        self.pending('QUEUED')
        self.assertEqual(poll_receipts(), (0, 0, 0))
        lookup.assert_not_called()

    @patch('automation_api.receipts.lookup', return_value={'found': False})
    def test_no_match_schedules_three_hours_and_skips_until_due(self, lookup):
        self.pending()
        self.assertEqual(poll_receipts(), (1, 0, 0))
        check = BirReceiptCheck.objects.get()
        self.assertEqual(check.next_check_at - check.last_checked_at, timedelta(minutes=1))
        self.assertEqual(poll_receipts(), (0, 0, 0))
        self.assertEqual(lookup.call_count, 1)

    @patch('automation_api.receipts.lookup')
    def test_receipt_is_durable_and_does_not_change_worker_result(self, lookup):
        order, approval = self.pending()
        lookup.return_value = {'found':True, 'filename':order.saved_xml_path.split('\\')[-1],
            'message':{'id':'abc123', 'date':timezone.now().isoformat(), 'text':'receipt'}}
        self.assertEqual(poll_receipts(), (1, 1, 0))
        approval.refresh_from_db()
        self.assertEqual(approval.state, 'SUBMITTED_WAITING_FOR_CONFIRMATION')
        self.assertEqual(WorkOrder.objects.get(pk=order.pk).operational_status, 'BIR receipt confirmation received')
        self.assertEqual(poll_receipts(), (0, 0, 0))

    @patch('automation_api.receipts.lookup', side_effect=subprocess.TimeoutExpired('node',120))
    def test_failure_is_visible_and_retryable(self, lookup):
        self.pending()
        self.assertEqual(poll_receipts(), (1, 0, 1))
        check = BirReceiptCheck.objects.get()
        self.assertTrue(check.last_error)
        self.assertIsNone(check.received_at)

    @patch('automation_api.receipts.lookup')
    def test_wrong_reference_or_old_receipt_is_rejected(self, lookup):
        order, approval = self.pending()
        lookup.return_value = {'found':True, 'filename':'wrong.xml',
            'message':{'id':'old', 'date':timezone.now().isoformat()}}
        self.assertEqual(poll_receipts(), (1, 0, 1))
        self.assertIsNone(BirReceiptCheck.objects.get().received_at)

    @patch('automation_api.receipts.lookup')
    def test_archived_filings_are_skipped(self, lookup):
        order, approval = self.pending()
        order.is_archived = True
        order.save(_service_write=True)
        self.assertEqual(poll_receipts(), (0, 0, 0))
        lookup.assert_not_called()
