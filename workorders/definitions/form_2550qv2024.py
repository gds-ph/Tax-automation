"""Contract for the supplied Stage1_Prepare_2550Q PAD flow."""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from .form_2551qv2018 import Definition2551Q

@dataclass(frozen=True)
class Definition2550Q(Definition2551Q):
    key: str = '2550qv2024_zero'
    form_code: str = '2550Q'
    form_version: str = '2024'
    expected_form_number: str = '2550Qv2024'
    form_selection_text: str = 'BIR Form 2550Qv2024 - Quarterly Value-Added (VAT) Tax Return'
    automation_key: str = 'PREPARE_2550QV2024_ZERO'

    def validate_profile(self, profile):
        if profile.calendar_or_fiscal != 'CALENDAR' or profile.year_end_month != '12':
            raise ValidationError('2550Qv2024 automation supports calendar years ending in December only.')

    def validate_data(self, data, *, require_atc=False):
        if data:
            raise ValidationError({'form_data': '2550Q automation supports only an original, full-quarter, Micro zero return without tax relief, amounts, credits or adjustments.'})
        return {}

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({'zero_filing': 'Only zero-filing 2550Qv2024 preparation is implemented.'})

DEFINITION = Definition2550Q()
