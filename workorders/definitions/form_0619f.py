"""Verified one-page 0619-F zero-remittance preparation contract."""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from .form_2551qv2018 import Definition2551Q


@dataclass(frozen=True)
class Definition0619F(Definition2551Q):
    key: str = '0619f_zero'
    form_code: str = '0619F'
    form_version: str = '2018'
    expected_form_number: str = '0619F'
    form_selection_text: str = 'BIR Form 0619F'
    automation_key: str = 'PREPARE_0619F_ZERO'
    filing_frequency: str = 'MONTHLY'

    def validate_profile(self, profile):
        pass

    def validate_data(self, data, *, require_atc=False):
        if data:
            raise ValidationError({'form_data': '0619-F currently supports only a non-amended private-agent return with no tax withheld, remittance or penalties.'})
        return {}

    def return_period(self, order):
        return f'{order.filing_month:02d}{order.filing_year}'

    def saved_return_name(self, order):
        return f'{order.combined_tin}-0619F-{self.return_period(order)}WB'

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({'zero_filing': 'Only zero-filing 0619-F preparation is implemented.'})


DEFINITION = Definition0619F()
