"""Explicit registry. Database keys select known definitions, never Python imports."""

from django.core.exceptions import ValidationError

from .form_2551qv2018 import DEFINITION as FORM_2551Q

DEFINITIONS = {FORM_2551Q.key: FORM_2551Q}


def get_definition(key):
    return DEFINITIONS.get(key)


def validate_period(frequency, year, month, quarter):
    if not isinstance(year, str) or len(year) != 4 or not year.isascii() or not year.isdigit() or year == "0000":
        raise ValidationError({"filing_year": "Enter a valid four-digit year."})
    if frequency == "QUARTERLY":
        if type(quarter) is not int or quarter not in (1, 2, 3, 4) or month is not None:
            raise ValidationError("Quarterly filings require quarter 1–4 and no month.")
    elif frequency == "MONTHLY":
        if type(month) is not int or month not in range(1, 13) or quarter is not None:
            raise ValidationError("Monthly filings require month 1–12 and no quarter.")
    elif frequency == "ANNUAL":
        if month is not None or quarter is not None:
            raise ValidationError("Annual filings must not specify a month or quarter.")
    else:
        raise ValidationError("The filing frequency is not supported.")


def validate_form_data(key, data, *, require_atc=False):
    if not isinstance(data, dict):
        raise ValidationError({"form_data": "Form data must be a JSON object."})
    definition = get_definition(key)
    if definition:
        return definition.validate_data(data, require_atc=require_atc)
    if data:
        raise ValidationError({"form_data": "This planned form has no validated data schema yet. Leave form data empty."})
    return {}
