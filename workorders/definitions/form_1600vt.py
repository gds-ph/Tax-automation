"""Verified one-page 1600-VT zero-remittance preparation contract."""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from .form_2551qv2018 import Definition2551Q


@dataclass(frozen=True)
class Definition1600VT(Definition2551Q):
    key: str = '1600vt_zero'
    form_code: str = '1600VT'
    form_version: str = '2018'
    expected_form_number: str = '1600VTv2018'
    form_selection_text: str = 'BIR Form 1600VTv2018'
    automation_key: str = 'PREPARE_1600VT_ZERO'
    filing_frequency: str = 'MONTHLY'

    def validate_profile(self, profile):
        pass

    def validate_data(self, data, *, require_atc=False):
        if data:
            raise ValidationError({'form_data': '1600-VT currently supports only a non-amended private-agent return with no tax withheld, remittance or penalties.'})
        return {}

    def return_period(self, order):
        return f'{order.filing_month:02d}{order.filing_year}'

    def saved_return_name(self, order):
        return f'{order.combined_tin}-1600VTv2018-{self.return_period(order)}'

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({'zero_filing': 'Only zero-filing 1600-VT preparation is implemented.'})


DEFINITION = Definition1600VT()
