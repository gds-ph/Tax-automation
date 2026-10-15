"""Private-agent original 1601EQ PAD contract."""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from .form_2551qv2018 import Definition2551Q

@dataclass(frozen=True)
class Definition1601EQ(Definition2551Q):
    key: str = 'cor_1601eq'
    form_code: str = '1601EQ'
    form_version: str = '2018'
    expected_form_number: str = '1601EQ'
    form_selection_text: str = 'BIR Form 1601EQ'
    automation_key: str = 'PREPARE_1601EQ_ZERO'
    filing_frequency: str = 'QUARTERLY'

    def validate_profile(self, profile):
        if profile.calendar_or_fiscal != 'CALENDAR' or profile.year_end_month != '12':
            raise ValidationError('1601EQ automation currently supports calendar years ending in December only.')

    def validate_data(self, data, *, require_atc=False):
        if isinstance(data, dict) and data.get('schema') == '1601eq-suppliers-v1':
            from ..quarterly_1601eq import normalize
            return normalize(data)
        if data:
            raise ValidationError({'form_data': 'Use a reviewed quarterly supplier worksheet for non-zero 1601EQ preparation.'})
        return {}

    def return_period(self, order):
        return f'{order.filing_year}Q{order.filing_quarter}'

    def validate_zero(self, zero_filing):
        if type(zero_filing) is not bool:
            raise ValidationError({'zero_filing': 'Choose a valid 1601EQ filing mode.'})

DEFINITION = Definition1601EQ()
