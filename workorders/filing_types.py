"""Supported filing workflows; add entries only with a validated implementation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FilingType:
    slug: str
    code: str
    title: str
    version: str
    selection_text: str
    period_label: str
    available: bool = True


FILING_2551Q = FilingType(
    slug="2551q", code="2551Q", title="Quarterly Percentage Tax Return",
    version="2551Qv2018", selection_text="BIR Form 2551Qv2018",
    period_label="Calendar-year · Quarterly · Zero filing",
)
FILING_TYPES = (FILING_2551Q,)
