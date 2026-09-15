from dataclasses import dataclass

from django.core.exceptions import ValidationError

from workorders.validators import normalize_atc, validate_atc_2551qv2018


@dataclass(frozen=True)
class Definition2551Q:
    key: str = "2551qv2018_zero"
    form_code: str = "2551Q"
    form_version: str = "2018"
    expected_form_number: str = "2551Qv2018"
    form_selection_text: str = "BIR Form 2551Qv2018"
    automation_key: str = "PREPARE_2551QV2018_ZERO"
    filing_frequency: str = "QUARTERLY"

    def validate_configuration(self, form):
        for field in ("form_code", "form_version", "expected_form_number", "form_selection_text", "automation_key", "filing_frequency"):
            if getattr(form, field) != getattr(self, field):
                raise ValidationError({field: f"The {self.key} definition requires {getattr(self, field)}."})

    def validate_profile(self, profile):
        if profile.calendar_or_fiscal != "CALENDAR" or profile.year_end_month != "12":
            raise ValidationError("2551Qv2018 currently supports calendar years ending in December only.")

    def validate_data(self, data, *, require_atc=False):
        if set(data) - {"atc_code"}:
            raise ValidationError({"form_data": "2551Qv2018 only supports the atc_code form-data field in this prototype."})
        result = dict(data)
        if "atc_code" in result:
            result["atc_code"] = normalize_atc(result["atc_code"])
            validate_atc_2551qv2018(result["atc_code"])
        elif require_atc:
            raise ValidationError({"form_data": "An explicit ATC is required for 2551Qv2018."})
        return result

    def return_period(self, order):
        return f"{order.year_end_month}{order.filing_year}Q{order.filing_quarter}"

    def saved_return_name(self, order):
        return f"{order.combined_tin}-{self.expected_form_number}-{self.return_period(order)}"

    def validate_zero(self, zero_filing):
        if zero_filing is not True:
            raise ValidationError({"zero_filing": "Only zero-filing 2551Qv2018 preparation is implemented."})


DEFINITION = Definition2551Q()
