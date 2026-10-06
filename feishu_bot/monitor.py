"""Background loop started by run_feishu_bot: approval, final-package and worker offline alerts against the
live dashboard, every FEISHU_BOT_APPROVAL_POLL_SECONDS."""
import logging
import time

from django.conf import settings
from django.db import close_old_connections

from . import approvals, feishu_api, live_dashboard, packages, worker_alerts

log = logging.getLogger(__name__)


def checks():
    """The checks that are switched on in settings, as (name, function)."""
    enabled = []
    if settings.FEISHU_BOT_APPROVAL_CHAT_ID:
        enabled.append(('approval', approvals.check_once))
        enabled.append(('package', packages.check_once))
    if settings.FEISHU_BOT_WORKER_ALERT_TO:
        enabled.append(('worker', worker_alerts.check_once))
    return enabled if live_dashboard.configured() else []


def watch():
    while True:
        for name, check in checks():
            close_old_connections()
            try:
                count = check()
                if count:
                    log.info('%s check: %s alert(s) sent', name.capitalize(), count)
            except (live_dashboard.LiveDashboardError, feishu_api.FeishuError) as exc:
                log.warning('%s check failed: %s', name.capitalize(), exc)
            except Exception:
                log.exception('%s check failed', name.capitalize())
            finally:
                close_old_connections()
        time.sleep(settings.FEISHU_BOT_APPROVAL_POLL_SECONDS)
