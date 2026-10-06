"""Structured events only: never accept request bodies, URLs or exception text."""
import logging
from django.db import DatabaseError
from .models import SystemLog

EVENTS = {'request', 'login', 'logout', 'login_failed', 'feishu_login_failed',
          'receipt_check', 'cor_scan', 'background_failed'}
COUNT_KEYS = {'checked', 'received', 'errors', 'ready', 'empty', 'total'}

def record(event, *, actor=None, level='INFO', route='', status=None, duration_ms=None, counts=None):
    if event not in EVENTS:
        raise ValueError('Unknown log event')
    safe_counts = {k: v for k, v in (counts or {}).items() if k in COUNT_KEYS and type(v) is int and v >= 0}
    try:
        SystemLog.objects.create(event=event, actor=actor if actor and actor.is_authenticated else None,
            level=level if level in {'INFO','WARNING','ERROR'} else 'INFO',
            route=route[:120], status=status, duration_ms=duration_ms, counts=safe_counts)
    except DatabaseError:
        logging.getLogger(__name__).warning('Operational log could not be saved; event=%s', event)
