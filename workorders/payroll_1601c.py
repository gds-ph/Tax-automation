"""Reviewed monthly payroll totals. Employee tax calculation stays in payroll."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError

KEY = 'PREPARE_1601CV2018_PAYROLL'
FIELDS = (
    ('compensation', '14 · Total compensation'),
    ('minimum_wage', '15 · Statutory minimum wage of MWEs'),
    ('mwe_benefits', '16 · Holiday, overtime, night shift and hazard pay of MWEs'),
    ('benefits', '17 · Exempt 13th-month pay and other benefits'),
    ('de_minimis', '18 · De minimis benefits'),
    ('contributions', '19 · Employee statutory contributions and union dues'),
    ('other_exempt', '20 · Other non-taxable compensation'),
    ('below_threshold', '23 · Taxable compensation not subject to withholding'),
    ('withheld', '25 · Tax withheld, calculated by payroll'),
)
MONEY = tuple(k for k, _ in FIELDS)


def normalize(data):
    allowed = set(MONEY) | {'other_exempt_description', 'schema', 'payroll_confirmed'}
    if not isinstance(data, dict) or set(data) - allowed or data.get('schema') != '1601c-payroll-v1':
        raise ValidationError('Unsupported 1601C payroll summary.')
    values = {}
    for key in MONEY:
        raw = data.get(key)
        try:
            if not isinstance(raw, str) or len(raw) > 20:
                raise ValueError
            value = Decimal(raw)
            if not value.is_finite() or value < 0 or value > Decimal('99999999999.99') or value != value.quantize(Decimal('.01')):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError(f'{dict(FIELDS)[key]} must be a non-negative amount with at most two decimals.')
        values[key] = format(value, '.2f')
    if Decimal(values['compensation']) <= 0:
        raise ValidationError('Enter positive compensation. Use zero filing when there is no compensation.')
    description = data.get('other_exempt_description', '')
    if not isinstance(description, str) or len(description) > 25 or any(ord(c) < 32 for c in description):
        raise ValidationError('Other non-taxable compensation description must be at most 25 characters, matching eBIRForms.')
    if Decimal(values['other_exempt']) and not description.strip():
        raise ValidationError('Describe the other non-taxable compensation.')
    if data.get('payroll_confirmed') not in (True, False) or type(data.get('payroll_confirmed')) is not bool:
        raise ValidationError('Payroll review confirmation is required.')
    values.update(schema='1601c-payroll-v1', other_exempt_description=description.strip(),
                  payroll_confirmed=data['payroll_confirmed'])
    totals(values)
    return values


def totals(data):
    d = {key: Decimal(data[key]) for key in MONEY}
    exempt = sum(d[k] for k in MONEY[1:7])
    taxable = d['compensation'] - exempt
    subject = taxable - d['below_threshold']
    if taxable < 0 or subject < 0:
        raise ValidationError('Exempt compensation and compensation not subject to withholding cannot exceed total compensation.')
    if d['withheld'] > subject:
        raise ValidationError('Tax withheld cannot exceed compensation subject to withholding.')
    return {k: format(v, '.2f') for k, v in {
        'exempt': exempt, 'taxable': taxable, 'subject': subject, 'due': d['withheld']}.items()}


def preparation_key(snapshot):
    filing = snapshot['filing']
    if snapshot['form']['expected_form_number'] == '1601Cv2018' and not filing['zero_filing']:
        return KEY
    if snapshot['form']['expected_form_number'] == '0619E' and not filing['zero_filing']:
        from .supplier_0619e import KEY as supplier_key
        return supplier_key
    if snapshot['form']['expected_form_number'] == '1601EQ' and not filing['zero_filing']:
        from .quarterly_1601eq import KEY as quarterly_key
        return quarterly_key
    return snapshot['form']['automation_key']
