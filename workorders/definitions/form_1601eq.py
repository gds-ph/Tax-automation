"""Private-agent, non-amended 1601EQ zero-return PAD contract."""
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
        if data:
            raise ValidationError({'form_data': '1601EQ currently supports only non-amended private-agent returns with no withholding, remittances, credits, penalties or attachments.'})
        return {}

    def return_period(self, order):
        return f'{order.filing_year}Q{order.filing_quarter}'

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({'zero_filing': 'Only zero-filing 1601EQ preparation is implemented.'})

DEFINITION = Definition1601EQ()
