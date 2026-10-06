"""Message chosen people privately when a live automation worker goes offline, and again when it is back.

Run by feishu_bot.monitor. It reads the Workers panel of the live dashboard with the bot's view-only account;
the dashboard calls a worker offline after two minutes without a heartbeat, or when it is disabled.
"""
import logging
import re

from django.conf import settings
from django.utils import timezone

from . import feishu_api, live_dashboard
from .models import WorkerStatus

log = logging.getLogger(__name__)


def _plain(text):
    return re.sub(r'[<>\[\]*_`~]', '', ' '.join(str(text).split()))[:160]


def offline_text(worker):
    return (f'⚠️ **Worker offline: {_plain(worker["name"])}**\n'
            f'Status: {_plain(worker["connection"])}'
            + (f' · {_plain(worker["heartbeat"])}' if worker.get('heartbeat') else '') + '\n'
            + (f'Activity: {_plain(worker["activity"])}\n' if worker.get('activity') else '')
            + 'Preparation and submission pause until it reconnects.\n'
            f'[Open work orders]({settings.FEISHU_BOT_SITE_URL}/work-orders/)')


def online_text(worker, since):
    down = timezone.localtime(since).strftime('%d %b %Y, %I:%M %p') if since else 'earlier'
    return f'✅ **Worker back online: {_plain(worker["name"])}** (offline since {down}).'


def _notify(text):
    for open_id in settings.FEISHU_BOT_WORKER_ALERT_TO:
        feishu_api.send_markdown(open_id, text, id_type='open_id')


def check_once():
    """Sends a message for each worker whose online state changed; returns how many changes were reported."""
    changes = 0
    for worker in live_dashboard.in_browser_thread(live_dashboard.worker_statuses):
        known = WorkerStatus.objects.filter(name=worker['name']).first()
        if known is None:
            # First sighting: an offline worker is reported, an online one is just remembered.
            if not worker['online']:
                _notify(offline_text(worker))
                changes += 1
            WorkerStatus.objects.create(name=worker['name'], online=worker['online'],
                                        connection=_plain(worker['connection']))
        elif known.online != worker['online']:
            _notify(offline_text(worker) if not worker['online'] else online_text(worker, known.changed_at))
            known.online, known.connection, known.changed_at = worker['online'], _plain(worker['connection']), timezone.now()
            known.save()  # only after the message went out, so a failed send is retried next time
            changes += 1
    return changes
