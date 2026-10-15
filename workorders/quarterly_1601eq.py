"""Immutable reviewed quarterly schedule for PAD preparation."""
from decimal import Decimal
from math import floor
from uuid import UUID
from django.core.exceptions import ValidationError
from .quarterly_withholding import calculate
KEY = 'PREPARE_1601EQ_SUPPLIERS'
SCHEMA = '1601eq-suppliers-v1'
AMOUNTS = ('first_remittance', 'second_remittance', 'surcharge', 'interest', 'compromise')

def preparation_totals(data):
    result = calculate(data.get('rows'), data.get('quarter'), **{k: data.get(k, '0') for k in AMOUNTS})
    transaction_total = Decimal(result['withheld'])
    withheld = Decimal('0')
    for group in result['groups']:
        group['transaction_tax'] = group['tax']
        # Match eBIRForms 7.9.6.1 getRequiredWithheld + string-util.js formatCurrency.
        # Preserve binary64 operation order and its rounding epsilon, including half-cent cases.
        value = float(group['base']) * float(group['rate']) / 100
        tax = Decimal(floor(value * 100 + 0.50000000001)) / 100
        group['rounding_adjustment'] = f"{tax - Decimal(group['tax']):.2f}"
        group['tax'] = f'{tax:.2f}'
        withheld += tax
    tax_due = withheld - Decimal(result['remittances'])
    result.update(transaction_withheld=f'{transaction_total:.2f}',
                  rounding_adjustment=f'{withheld - transaction_total:.2f}',
                  has_rounding_adjustment=any(Decimal(g['rounding_adjustment']) != 0 for g in result['groups']),
                  withheld=f'{withheld:.2f}', tax_due=f'{tax_due:.2f}',
                  due=f"{tax_due + Decimal(result['penalties']):.2f}")
    return result

def normalize(data):
    allowed = {'schema', 'quarter', 'rows', 'schedule_confirmed', 'draft_id', 'draft_version', *AMOUNTS}
    if not isinstance(data, dict) or set(data) - allowed or data.get('schema') != SCHEMA:
        raise ValidationError('Unsupported quarterly supplier data.')
    if type(data.get('schedule_confirmed')) is not bool:
        raise ValidationError('Quarterly review confirmation is required.')
    try:
        draft_id = str(UUID(data['draft_id']))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValidationError('A saved quarterly draft is required.')
    if type(data.get('draft_version')) is not int or data['draft_version'] < 1:
        raise ValidationError('Invalid quarterly draft revision.')
    result = preparation_totals(data)
    if len(result['groups']) > 6:
        raise ValidationError('PAD preparation supports up to six ATCs. Additional schedules are not connected yet.')
    if Decimal(result['tax_due']) < 0:
        raise ValidationError('Over-remittance disposition requires manual preparation.')
    if any(Decimal(result[k]) > Decimal('999999999.99') for k in ('withheld', 'due', *AMOUNTS)) or any(Decimal(g['base']) > Decimal('999999999.99') for g in result['groups']):
        raise ValidationError('Quarterly amounts exceed the supported PAD range.')
    return dict(schema=SCHEMA, quarter=data['quarter'], rows=result['rows'], schedule_confirmed=data['schedule_confirmed'], draft_id=draft_id, draft_version=data['draft_version'], **{k: result[k] for k in AMOUNTS})

def totals(data):
    clean = normalize(data)
    return preparation_totals(clean)
