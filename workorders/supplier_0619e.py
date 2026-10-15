"""Immutable reviewed supplier schedule for original private-agent 0619E."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from .expanded_withholding import normalize_rows, total

KEY = 'PREPARE_0619E_SUPPLIERS'
SCHEMA = '0619e-suppliers-v1'


def normalize(data):
    allowed = {'schema', 'rows', 'schedule_confirmed', 'draft_id', 'draft_version'}
    if not isinstance(data, dict) or set(data) - allowed or data.get('schema') != SCHEMA:
        raise ValidationError('Unsupported 0619E supplier schedule.')
    rows = data.get('rows')
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValidationError('Enter supplier transactions.')
    rows = normalize_rows(rows)
    if not Decimal('0') < total(rows) <= Decimal('999999999.99'):
        raise ValidationError('Total withholding must be positive and no more than 999,999,999.99.')
    if type(data.get('schedule_confirmed')) is not bool:
        raise ValidationError('Supplier schedule confirmation is required.')
    import uuid
    try:
        draft_id = str(uuid.UUID(data['draft_id']))
        if type(data['draft_version']) is not int or data['draft_version'] < 1:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValidationError('A saved supplier schedule revision is required.')
    return dict(schema=SCHEMA, rows=rows, schedule_confirmed=data['schedule_confirmed'],
                draft_id=draft_id, draft_version=data['draft_version'])


def withholding(data):
    return format(total(normalize(data)['rows']), '.2f')
