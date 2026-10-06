import ntpath
import re
import subprocess
import smtplib
from email.message import EmailMessage
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import BirReceiptCheck, Stage2Approval
from .gmail_receipts import lookup_receipt
from .finalize_receipt import finalize
from .models import GmailMailbox
from audit.models import SystemSetting

WAITING = 'SUBMITTED_WAITING_FOR_CONFIRMATION'
RETRY_INTERVAL = timedelta(minutes=1)


def _trrc_period(order):
    return order.period_label


def send_trrc_escalation(check):
    """Send a follow-up for a submitted return missing its TRRC."""
    order = check.approval.work_order
    from workorders.contact_defaults import TEST_CLIENT_CODES
    # Check both the retained filing identity and the current client identity.
    is_test = (order.legacy_client_reference in TEST_CLIENT_CODES or
               (order.client_id and order.client.client_code in TEST_CLIENT_CODES))
    recipient = ('heiner@gds.ph' if is_test else
                 (SystemSetting.objects.filter(key='trrc_escalation_recipient').values_list('value', flat=True).first()
                  or settings.TRRC_ESCALATION_RECIPIENT))
    mailbox = GmailMailbox.current()
    sender = mailbox.address if mailbox else settings.GMAIL_ADDRESS
    password = mailbox.app_password() if mailbox else settings.GMAIL_APP_PASSWORD
    if not recipient or not sender or not password:
        raise RuntimeError('TRRC escalation email is not configured.')
    period = _trrc_period(order)
    subject = f'NO TRRC RECEIVED FOR FORM {order.form_code} {period}'
    tin = f'{order.tin1}-{order.tin2}-{order.tin3}-{order.tin4}'
    sent_date = timezone.localtime(check.submitted_after)
    sent_at = f'{sent_date:%B} {sent_date.day}, {sent_date:%Y}'
    body = (f'Dear Revenue Officer,\n\nGood day!\n\n'
            f'We would like to confirm the receipt of {period} {order.form_code} for the '
            f'following company which we haven\'t received a copy of the Tax Return Receipt '
            f'Confirmation (TRRC).\n\n'
            f'TIN: {tin}\nCOMPANY NAME: {order.registered_name}\n'
            f'FORM / DOCUMENT FILED: BIR FORM {order.form_code}\n'
            f'DATE FILED / SENT: {sent_at}\nRETURN PERIOD / PERIOD COVERED: {period}\n'
            f'EMAIL ADDRESS USED: {sender}\nCONTACT NO.: {order.telephone_number or "N/A"}\n\n'
            'We wish for your response regarding the matter. Thank you and God Bless\n\n'
            f'Best Regards,\n{order.registered_name}')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = subject
    message.set_content(body)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)
    return recipient


def escalate_overdue_trrc():
    """Escalate eligible checks for all tracked forms after the configured delay."""
    configured = SystemSetting.objects.filter(key='trrc_escalation_after_minutes').values_list('value', flat=True).first()
    minutes = int(configured) if configured and configured.isdigit() else settings.TRRC_ESCALATION_AFTER_MINUTES
    delay = (timedelta(minutes=minutes)
             if minutes > 0
             else timedelta(days=settings.TRRC_ESCALATION_AFTER_DAYS))
    cutoff = timezone.now() - delay
    sent = errors = 0
    due = BirReceiptCheck.objects.select_related('approval__work_order').filter(
        approval__state=WAITING, approval__submission_enabled=True,
        approval__work_order__is_archived=False, received_at__isnull=True,
        trrc_escalation_sent_at__isnull=True, submitted_after__lte=cutoff)
    for pk in list(due.values_list('pk', flat=True)):
        check = BirReceiptCheck.objects.select_related('approval__work_order').get(pk=pk)
        try:
            recipient = send_trrc_escalation(check)
            with transaction.atomic():
                current = BirReceiptCheck.objects.select_for_update().get(pk=pk)
                if current.trrc_escalation_sent_at is None:
                    current.trrc_escalation_sent_at = timezone.now()
                    current.trrc_escalation_recipient = recipient
                    current.trrc_escalation_error = ''
                    current.save(update_fields=['trrc_escalation_sent_at', 'trrc_escalation_recipient', 'trrc_escalation_error'])
                    sent += 1
        except (OSError, smtplib.SMTPException, RuntimeError):
            errors += 1
            BirReceiptCheck.objects.filter(pk=pk, trrc_escalation_sent_at__isnull=True).update(
                trrc_escalation_error='TRRC escalation email failed; it will be retried.')
    return sent, errors


def discover_pending():
    for approval in Stage2Approval.objects.select_related('work_order', 'attempt').filter(
            state=WAITING, submission_enabled=True, work_order__is_archived=False):
        filename = ntpath.basename(approval.work_order.saved_xml_path)
        # Use the actual saved filename; never guess version suffixes from PDF fields.
        if not (re.fullmatch(r'\d{12,15}-[A-Za-z0-9]+-\d{4,6}(?:Q[1-4])?(?:V\d+)?\.xml', filename)
                or re.fullmatch(r'\d{12,15}-0619F-(?:0[1-9]|1[0-2])\d{4}WB\.xml', filename)):
            continue
        BirReceiptCheck.objects.get_or_create(approval=approval, defaults={
            'filename': filename,
            'submitted_after': approval.attempt.started_at if approval.attempt else approval.approved_at,
        })


def lookup(check):
    result = lookup_receipt(check.filename, check.submitted_after)
    if result.get('found'):
        return result
    from workorders.contact_defaults import TEST_CLIENT_CODES
    order = check.approval.work_order
    if (order.legacy_client_reference in TEST_CLIENT_CODES or
            (order.client_id and order.client.client_code in TEST_CLIENT_CODES)):
        result = lookup_receipt(check.filename, check.submitted_after, sender='heiner@gds.ph')
        if result.get('found'):
            result['test_receipt'] = True
    return result


def poll_receipts():
    discover_pending()
    configured = SystemSetting.objects.filter(key='receipt_check_interval_minutes').values_list('value', flat=True).first()
    interval = timedelta(minutes=int(configured)) if configured and configured.isascii() and configured.isdigit() and 1 <= int(configured) <= 1440 else RETRY_INTERVAL
    checked = received = errors = 0
    now = timezone.now()
    due = BirReceiptCheck.objects.filter(received_at__isnull=True, next_check_at__lte=now,
        approval__state=WAITING, approval__submission_enabled=True, approval__work_order__is_archived=False)
    for pk in list(due.values_list('pk', flat=True)):
        # Atomic reservation prevents overlapping scheduled processes querying the same filing.
        if not BirReceiptCheck.objects.filter(pk=pk, received_at__isnull=True, next_check_at__lte=now).update(
                next_check_at=now + timedelta(minutes=10)):
            continue
        check = BirReceiptCheck.objects.get(pk=pk)
        checked += 1
        try:
            result = lookup(check)
            if not isinstance(result, dict) or not isinstance(result.get('found'), bool):
                raise ValueError('Invalid bridge result')
            message = result.get('message', {})
            received_at = parse_datetime(message.get('date', '')) if result['found'] else None
            if result['found'] and (result.get('filename') != check.filename or not message.get('id') or
                    not received_at or timezone.is_naive(received_at) or received_at < check.submitted_after):
                raise ValueError('Invalid receipt evidence')
            with transaction.atomic():
                current = BirReceiptCheck.objects.select_for_update().get(pk=pk)
                if current.received_at:
                    continue
                current.last_checked_at = timezone.now()
                current.next_check_at = current.last_checked_at + interval
                current.last_error = ''
                if result['found']:
                    current.received_at = received_at
                    current.message_id = message['id']
                    current.evidence = result
                    received += 1
                current.save()
            if result['found'] and check.approval.success_screenshot:
                finalize(BirReceiptCheck.objects.select_related('approval__work_order', 'approval__attempt').get(pk=pk))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError, RuntimeError):
            errors += 1
            BirReceiptCheck.objects.filter(pk=pk, received_at__isnull=True).update(
                last_checked_at=timezone.now(), next_check_at=timezone.now() + interval,
                last_error='Email check failed. Connect Gmail from the dashboard and retry.')
    escalated, escalation_errors = escalate_overdue_trrc()
    return checked, received, errors + escalation_errors
