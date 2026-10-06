"""Post a Feishu alert when a live work order starts awaiting submission approval, @mentioning its creator.

Run by feishu_bot.monitor in run_feishu_bot's background loop. It reads the live dashboard's work-order list with the bot's
view-only account (feishu_bot.live_dashboard) and announces each work order once (ApprovalAlert).
"""
import logging
import re

from django.conf import settings

from . import feishu_api, live_dashboard
from .models import ApprovalAlert

log = logging.getLogger(__name__)

MAX_PER_RUN = 10
SUMMARY_LINES = 20
WORK_ORDER = re.compile(r'/work-orders/([0-9a-fA-F-]{36})/')
OPEN_ID = re.compile(r'ou_[A-Za-z0-9]{8,64}')


def mentions():
    """{normalised dashboard name: Feishu open_id}: members of the alert chat whose Feishu name equals their
    dashboard name, plus FEISHU_BOT_APPROVAL_MENTIONS ("NAME=ou_x; NAME=ou_y") for names that differ.
    Empty while FEISHU_BOT_ALERT_MENTIONS is off, so every creator is shown as a bold name."""
    found = {}
    if not settings.FEISHU_BOT_ALERT_MENTIONS:
        return found
    try:
        for name, open_id in feishu_api.chat_members(settings.FEISHU_BOT_APPROVAL_CHAT_ID):
            if name and OPEN_ID.fullmatch(open_id or ''):
                found[_normal(name)] = open_id
    except feishu_api.FeishuError:
        pass  # without the member list, mapped names still work and the rest are shown in bold
    for pair in settings.FEISHU_BOT_APPROVAL_MENTIONS.split(';'):
        name, _, open_id = pair.partition('=')
        if name.strip() and OPEN_ID.fullmatch(open_id.strip()):
            found[_normal(name)] = open_id.strip()
    return found


def _normal(name):
    return ' '.join(name.split()).casefold()


def _plain(text):
    # Dashboard text goes into card markdown: drop characters that could form links, mentions or formatting.
    return re.sub(r'[<>\[\]*_`~]', '', ' '.join(str(text).split()))[:120]


def _who(name, known):
    open_id = known.get(_normal(name))
    return f'<at id={open_id}></at>' if open_id else f'**{_plain(name) or "unknown"}**'


def _link(row):
    return f'{settings.FEISHU_BOT_SITE_URL}{row["path"]}#submission-review'


def alert_text(row, known):
    return (f'🔔 **Awaiting submission approval**\n'
            f'**{_plain(row["client"])}** · {_plain(row["form"])} · {_plain(row["period"])}\n'
            f'Created by {_who(row["created_by"], known)}\n'
            f'[Review for approval]({_link(row)})')


def summary_text(rows, known):
    lines = [f'{n}. **{_plain(r["client"])}** · {_plain(r["form"])} {_plain(r["period"])} · created by '
             f'{_who(r["created_by"], known)} · [Review]({_link(r)})' for n, r in enumerate(rows[:SUMMARY_LINES], 1)]
    more = f'\n…and {len(rows) - SUMMARY_LINES} more on the dashboard.' if len(rows) > SUMMARY_LINES else ''
    return (f'🔔 **Work orders awaiting submission approval ({len(rows)})**\n' + '\n'.join(lines) + more +
            '\n\nFrom now on I will post each new one here as it arrives.')


def _record(row, key, chat, message_id):
    ApprovalAlert.objects.get_or_create(work_order=key, defaults={
        'client': _plain(row['client']), 'created_by': _plain(row['created_by']), 'chat_id': chat,
        'message_id': message_id or ''})


def check_once():
    """Announces work orders not announced before; returns how many were announced."""
    chat = settings.FEISHU_BOT_APPROVAL_CHAT_ID
    first_run = not ApprovalAlert.objects.exists()
    skip = settings.FEISHU_BOT_APPROVAL_SKIP_CLIENTS
    new = []
    for row in live_dashboard.in_browser_thread(live_dashboard.awaiting_approvals):
        if skip and re.search(skip, row['client'], re.IGNORECASE):
            continue  # test clients are never announced
        match = WORK_ORDER.fullmatch(row['path'])
        if match and not ApprovalAlert.objects.filter(work_order=match.group(1)).exists():
            new.append((row, match.group(1)))
    if not new:
        return 0
    known = mentions()
    if first_run and len(new) > 1:
        # The existing backlog is announced once as a single message rather than one message each.
        message_id = feishu_api.send_markdown(chat, summary_text([row for row, _ in new], known))
        for row, key in new:
            _record(row, key, chat, message_id)
        return len(new)
    sent = 0
    for row, key in new[:MAX_PER_RUN]:
        message_id = feishu_api.send_markdown(chat, alert_text(row, known))
        _record(row, key, chat, message_id)  # only after a successful post, so a failed post is retried next time
        sent += 1
    return sent

