"""Queue policy: automated full-period returns must cover a completed period."""
from calendar import monthrange
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.utils import timezone


def manila_today():
    return timezone.localdate(timezone=ZoneInfo('Asia/Manila'))


def validate_completed_period(frequency, year, month=None, quarter=None, *, today=None):
    today = today or manila_today()
    if frequency == 'MONTHLY':
        end_month = int(month)
    elif frequency == 'QUARTERLY':
        end_month = int(quarter) * 3
    else:
        raise ValidationError('This filing frequency is not supported by the preparation queue.')
    end = date(int(year), end_month, monthrange(int(year), end_month)[1])
    if end >= today:
        field = 'filing_month' if frequency == 'MONTHLY' else 'filing_quarter'
        available = (end + timedelta(days=1)).strftime('%d %b %Y') if end.year < 9999 else 'after this period ends'
        raise ValidationError({field: f'Advance filing is not available. This period ends on {end:%d %b %Y}; queue it from {available} (Manila time). Choose a completed period.'})


def default_completed_period(frequency, *, today=None):
    today = today or manila_today()
    start_month = today.month if frequency == 'MONTHLY' else ((today.month - 1) // 3) * 3 + 1
    previous = date(today.year, start_month, 1) - timedelta(days=1)
    return {'filing_year': str(previous.year), 'filing_month': previous.month,
            'filing_quarter': (previous.month - 1) // 3 + 1}
