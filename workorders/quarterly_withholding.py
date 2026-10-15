"""Review-only 1601EQ worksheet. Never creates worker tasks or payment evidence."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from .atc_catalog import ATC_BY_CODE
from .expanded_withholding import normalize_rows, number, total


def calculate(rows, quarter, first_remittance='0', second_remittance='0', surcharge='0', interest='0', compromise='0'):
    if type(quarter) is not int or quarter not in (1, 2, 3, 4):
        raise ValidationError('Choose a valid quarter.')
    if not isinstance(rows, list) or not rows or len(rows) > 500:
        raise ValidationError('Enter 1 to 500 supplier transactions.')
    normalized = []
    groups = {}
    months = range(quarter * 3 - 2, quarter * 3 + 1)
    for raw in rows:
        if not isinstance(raw, dict) or type(raw.get('month')) is not int or raw['month'] not in months:
            raise ValidationError('Every transaction month must belong to the selected quarter.')
        atc = str(raw.get('atc', '')).strip().upper()
        if atc not in ATC_BY_CODE:
            raise ValidationError('Choose an ATC from the supported catalog.')
        # Rates and tax amounts are computed on the server, never accepted from the browser.
        row = normalize_rows([{**raw, 'atc': atc, 'rate': ATC_BY_CODE[atc]['rate'], 'tax': ''}])[0]
        row['month'] = raw['month']
        normalized.append(row)
        group = groups.setdefault(atc, {'atc': atc, 'rate': row['rate'], 'base': Decimal(0), 'tax': Decimal(0)})
        group['base'] += Decimal(row['base'])
        group['tax'] += Decimal(row['tax'])
    withheld = total(normalized)
    if withheld <= 0:
        raise ValidationError('Enter positive withholding; use zero filing for a zero return.')
    first = number(first_remittance, 'First-month remittance', Decimal('999999999999.99'))
    second = number(second_remittance, 'Second-month remittance', Decimal('999999999999.99'))
    surcharge = number(surcharge or '0', 'Surcharge', Decimal('999999999999.99'))
    interest = number(interest or '0', 'Interest', Decimal('999999999999.99'))
    compromise = number(compromise or '0', 'Compromise', Decimal('999999999999.99'))
    penalties = surcharge + interest + compromise
    tax_due = withheld - first - second
    return {'rows': normalized, 'groups': [{**g, 'base': f"{g['base']:.2f}", 'tax': f"{g['tax']:.2f}"} for g in groups.values()],
            'withheld': f'{withheld:.2f}', 'first_remittance': f'{first:.2f}', 'second_remittance': f'{second:.2f}',
            'remittances': f'{first + second:.2f}', 'tax_due': f'{tax_due:.2f}', 'surcharge': f'{surcharge:.2f}', 'interest': f'{interest:.2f}', 'compromise': f'{compromise:.2f}', 'penalties': f'{penalties:.2f}', 'due': f'{tax_due + penalties:.2f}'}
