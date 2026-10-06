"""The tested private-agent, no-compensation/no-adjustments PAD preparation."""
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .form_2551qv2018 import Definition2551Q


@dataclass(frozen=True)
class Definition1601C(Definition2551Q):
    key: str = '1601cv2018_zero'
    form_code: str = '1601C'
    form_version: str = '2018'
    expected_form_number: str = '1601Cv2018'
    form_selection_text: str = 'BIR Form 1601Cv2018'
    automation_key: str = 'PREPARE_1601CV2018_ZERO'
    filing_frequency: str = 'MONTHLY'

    def validate_profile(self, profile):
        # Month/year identity does not depend on the accounting year end.
        pass

    def validate_data(self, data, *, require_atc=False):
        if data:
            raise ValidationError({'form_data': '1601C currently supports only private-agent preparation with no compensation, withholding, attachments, tax relief or prior-month adjustments.'})
        return {}

    def return_period(self, order):
        return f'{order.filing_month:02d}{order.filing_year}'

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({'zero_filing': 'Only the tested zero-compensation 1601C preparation is implemented.'})


DEFINITION = Definition1601C()
