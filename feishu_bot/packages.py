"""Post a Feishu alert when a live work order's final filing package is generated from a real BIR receipt,
@mentioning its creator in the approval-alert chat.

Run by feishu_bot.monitor. It reads the live dashboard's "Completed this month" list with the bot's view-only
account. Packages that already existed when this was switched on are recorded quietly, never announced.
"""
import logging
import re

from django.conf import settings

from . import approvals, feishu_api, live_dashboard
from .models import PackageAlert

log = logging.getLogger(__name__)

MAX_PER_RUN = 10
# Only packages built from the real BIR receipt email; simulated receipts read "Simulation complete - ...".
REAL_PACKAGE = 'Receipt package generated'


def alert_text(row, known):
    return (f'📦 **Full filing package ready**\n'
            f'**{approvals._plain(row["client"])}** · {approvals._plain(row["form"])} · '
            f'{approvals._plain(row["period"])}\n'
            f'BIR receipt confirmed · created by {approvals._who(row["created_by"], known)}\n'
            f'[Open work order]({settings.FEISHU_BOT_SITE_URL}{row["path"]})')


def check_once():
    """Announces packages not seen before; returns how many were announced."""
    chat = settings.FEISHU_BOT_APPROVAL_CHAT_ID
    first_run = not PackageAlert.objects.exists()
    skip = settings.FEISHU_BOT_APPROVAL_SKIP_CLIENTS
    new = []
    for row in live_dashboard.in_browser_thread(live_dashboard.completed_packages):
        if row.get('status') != REAL_PACKAGE or (skip and re.search(skip, row['client'], re.IGNORECASE)):
            continue
        match = approvals.WORK_ORDER.fullmatch(row['path'])
        if match and not PackageAlert.objects.filter(work_order=match.group(1)).exists():
            new.append((row, match.group(1)))
    if first_run:
        # Switching the alert on: remember what already exists without announcing it.
        for row, key in new:
            PackageAlert.objects.get_or_create(work_order=key, defaults={
                'client': approvals._plain(row['client']), 'created_by': approvals._plain(row['created_by']),
                'announced': False})
        if not new:
            # An empty marker so the next check is not mistaken for the first one.
            PackageAlert.objects.get_or_create(work_order='-', defaults={'announced': False})
        return 0
    if not new:
        return 0
    known = approvals.mentions()
    sent = 0
    for row, key in new[:MAX_PER_RUN]:
        message_id = feishu_api.send_markdown(chat, alert_text(row, known))
        PackageAlert.objects.get_or_create(work_order=key, defaults={
            'client': approvals._plain(row['client']), 'created_by': approvals._plain(row['created_by']),
            'chat_id': chat, 'message_id': message_id or ''})  # only after a successful post
        sent += 1
    return sent
