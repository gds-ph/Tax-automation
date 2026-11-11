"""Original private-agent 1601-FQ zero-filing contract (installed January 2018 form)."""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from .form_2551qv2018 import Definition2551Q


@dataclass(frozen=True)
class Definition1601FQ(Definition2551Q):
    key: str = '1601fq_zero'
    form_code: str = '1601FQ'
    form_version: str = '2018'
    expected_form_number: str = '1601FQ'
    form_selection_text: str = 'BIR Form 1601FQ'
    automation_key: str = 'PREPARE_1601FQ_ZERO'
    filing_frequency: str = 'QUARTERLY'

    def validate_profile(self, profile):
        if profile.calendar_or_fiscal != 'CALENDAR' or profile.year_end_month != '12':
            raise ValidationError('1601FQ automation supports calendar years ending in December only.')

    def validate_data(self, data, *, require_atc=False):
        if data:
            raise ValidationError({'form_data': '1601FQ supports only an original private-agent zero return with no withholding, remittances, credits, penalties, treaty claims or attachments.'})
        return {}

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({'zero_filing': 'Only zero-filing 1601FQ preparation is implemented.'})

    def return_period(self, order):
        return f'{order.filing_year}Q{order.filing_quarter}'


DEFINITION = Definition1601FQ()
