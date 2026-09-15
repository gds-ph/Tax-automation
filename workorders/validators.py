"""Normalization and structural validators for the current 2551Qv2018 flow."""

import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .reference_data.atc_2551qv2018 import ALLOWED_ATCS

tin_segment = RegexValidator(r"\A[0-9]{3}\Z", "Enter exactly three numeric digits.")
tin_branch = RegexValidator(r"\A[0-9]{5}\Z", "Enter exactly five numeric branch digits.")
rdo_code = RegexValidator(r"\A[0-9A-Z]{3}\Z", "Enter three uppercase letters or digits, such as 047 or 53A.")
filing_year = RegexValidator(r"\A[0-9]{4}\Z", "Enter a four-digit filing year.")
sha256_hex = RegexValidator(r"\A[0-9a-f]{64}\Z", "Enter a lowercase SHA-256 digest.")


def normalize_rdo(value: str) -> str:
    return value.strip().upper() if isinstance(value, str) else value


def normalize_atc(value: str) -> str:
    if not isinstance(value, str):
        return value
    value = value.strip().upper()
    if re.fullmatch(r"PT[0-9]{3}", value):
        value = f"PT {value[2:]}"
    return value


def validate_atc_2551qv2018(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"PT [0-9]{3}", value):
        raise ValidationError("ATC is required in the format PT 010.")
    if value not in ALLOWED_ATCS:
        raise ValidationError("This ATC is not supported by the configured 2551Qv2018 Schedule 1 list.")


def safe_filename_component(value: str) -> str:
    """Produce a bounded Windows-safe component, including reserved-name handling."""
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value).strip(" ._")[:100].rstrip(" .")
    if not value:
        return "CLIENT"
    stem = value.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
        value = "_" + value
    return value
