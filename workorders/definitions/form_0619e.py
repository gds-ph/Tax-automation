"""Verified one-page, original private-agent zero 0619-E preparation."""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from .form_0619f import Definition0619F

@dataclass(frozen=True)
class Definition0619E(Definition0619F):
    key: str = '0619e_zero'
    form_code: str = '0619E'
    expected_form_number: str = '0619E'
    form_selection_text: str = 'BIR Form 0619E'
    automation_key: str = 'PREPARE_0619E_ZERO'

    def validate_data(self, data, *, require_atc=False):
        if data and data.get('schema') == '0619e-suppliers-v1':
            from workorders.supplier_0619e import normalize
            return normalize(data)
        if data:
            raise ValidationError({'form_data': '0619-E supports only an original private-agent return with no withholding, remittance or penalties.'})
        return {}

    def validate_zero(self, zero_filing):
        if type(zero_filing) is not bool:
            raise ValidationError({'zero_filing': 'Only zero-filing 0619-E preparation is implemented.'})

    def saved_return_name(self, order):
        return f'{order.combined_tin}-0619E-{self.return_period(order)}'

DEFINITION = Definition0619E()
