import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from . import validators
from .contact_defaults import DEFAULT_RDO_EMAIL
from .definitions import get_definition, validate_form_data
from .model_support import ServiceModel

CLIENT_FIELDS = (
    "client_code", "client_type", "registered_name", "trade_name", "tin1", "tin2", "tin3", "tin4",
    "rdo_code", "registered_address", "zip_code", "telephone_number", "email_address", "rdo_email", "line_of_business",
    "client_folder_path", "is_active",
)
FORM_FIELDS = (
    "form_code", "form_version", "expected_form_number", "display_name", "form_selection_text",
    "filing_frequency", "automation_key", "preparation_automation_available", "submission_automation_available",
    "is_active", "definition_key",
)
PROFILE_FIELDS = ("is_active", "year_end_month", "calendar_or_fiscal", "default_atc_code", "default_form_data")


class Client(ServiceModel):
    class Type(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        NON_INDIVIDUAL = "NON_INDIVIDUAL", "Non-individual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_code = models.CharField(max_length=80, unique=True)
    client_type = models.CharField(max_length=20, choices=Type.choices)
    registered_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    tin1 = models.CharField(max_length=3, validators=[validators.tin_segment])
    tin2 = models.CharField(max_length=3, validators=[validators.tin_segment])
    tin3 = models.CharField(max_length=3, validators=[validators.tin_segment])
    tin4 = models.CharField(max_length=5, validators=[validators.tin_branch])
    rdo_code = models.CharField(max_length=3, validators=[validators.rdo_code])
    registered_address = models.TextField(max_length=2000)
    zip_code = models.CharField(max_length=20)
    telephone_number = models.CharField(max_length=50, blank=True)
    email_address = models.EmailField(blank=True)
    rdo_email = models.EmailField("RDO email", blank=True, default=DEFAULT_RDO_EMAIL)
    line_of_business = models.CharField(max_length=200)
    client_folder_path = models.CharField(max_length=500, blank=True, help_text="Automation-VM-local metadata only; Django never opens this path.")
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("registered_name", "client_code")
        constraints = [models.CheckConstraint(condition=models.Q(client_type__in=["INDIVIDUAL", "NON_INDIVIDUAL"]), name="client_valid_type"),
                       models.CheckConstraint(condition=models.Q(version__gte=1), name="client_positive_version")]

    @property
    def display_name(self):
        return self.trade_name or self.registered_name

    @property
    def combined_tin(self):
        return self.tin1 + self.tin2 + self.tin3 + self.tin4

    def clean_fields(self, exclude=None):
        self.rdo_code = validators.normalize_rdo(self.rdo_code)
        errors = {}
        for field in CLIENT_FIELDS:
            if field == "is_active":
                continue
            value = getattr(self, field)
            if not isinstance(value, str):
                errors[field] = "Supply text so leading zeros are preserved."
            elif field not in {"trade_name", "client_folder_path", "telephone_number", "email_address", "rdo_email"} and not value.strip():
                errors[field] = "This field is required."
        if errors:
            raise ValidationError(errors)
        super().clean_fields(exclude=exclude)

    def __str__(self):
        return f"{self.client_code} — {self.display_name}"


class FormDefinition(ServiceModel):
    class Frequency(models.TextChoices):
        QUARTERLY = "QUARTERLY", "Quarterly"
        MONTHLY = "MONTHLY", "Monthly"
        ANNUAL = "ANNUAL", "Annual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form_code = models.CharField(max_length=20)
    form_version = models.CharField(max_length=30, blank=True)
    expected_form_number = models.CharField(max_length=30, blank=True)
    display_name = models.CharField(max_length=200)
    form_selection_text = models.CharField(max_length=100, blank=True)
    filing_frequency = models.CharField(max_length=12, choices=Frequency.choices)
    automation_key = models.CharField(max_length=100, blank=True)
    preparation_automation_available = models.BooleanField(default=False)
    submission_automation_available = models.BooleanField(default=False, editable=False)
    is_active = models.BooleanField(default=True)
    definition_key = models.CharField(max_length=100, unique=True)
    version = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("form_code", "form_version")
        constraints = [
            models.UniqueConstraint(fields=("form_code", "form_version"), name="form_unique_version"),
            models.CheckConstraint(condition=models.Q(submission_automation_available=False), name="form_submission_disabled"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="form_positive_version"),
        ]

    def clean(self):
        definition = get_definition(self.definition_key)
        if definition:
            definition.validate_configuration(self)
        elif self.preparation_automation_available or self.automation_key:
            raise ValidationError("Unimplemented definitions must have preparation disabled and an empty automation key.")
        if self.submission_automation_available:
            raise ValidationError("Submission automation is disabled.")

    def __str__(self):
        return f"{self.form_code} — {self.display_name}" + (" (Not yet automated)" if not self.preparation_automation_available else "")


class ClientFilingProfile(ServiceModel):
    class Basis(models.TextChoices):
        CALENDAR = "CALENDAR", "Calendar"
        FISCAL = "FISCAL", "Fiscal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="filing_profiles")
    form_definition = models.ForeignKey(FormDefinition, on_delete=models.PROTECT, related_name="client_profiles")
    is_active = models.BooleanField(default=True)
    year_end_month = models.CharField(max_length=2, default="12", validators=[RegexValidator(r"\A(?:0[1-9]|1[0-2])\Z", "Enter a two-digit month from 01 to 12.")])
    calendar_or_fiscal = models.CharField(max_length=8, choices=Basis.choices, default=Basis.CALENDAR)
    default_atc_code = models.CharField(max_length=30, null=True, blank=True, default=None)
    default_form_data = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("client__registered_name", "form_definition__form_code")
        constraints = [
            models.UniqueConstraint(fields=("client", "form_definition"), name="unique_client_form_profile"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="profile_positive_version"),
        ]

    def clean_fields(self, exclude=None):
        if self.default_atc_code == "":
            self.default_atc_code = None
        if self.default_atc_code is not None:
            self.default_atc_code = validators.normalize_atc(self.default_atc_code)
        if not isinstance(self.year_end_month, str):
            raise ValidationError({"year_end_month": "Supply the month as two-digit text."})
        super().clean_fields(exclude=exclude)

    def clean(self):
        if not self.form_definition_id:
            return
        form = self.form_definition
        definition = get_definition(form.definition_key)
        if self.calendar_or_fiscal == self.Basis.CALENDAR and self.year_end_month != "12":
            raise ValidationError({"year_end_month": "Calendar years end in month 12."})
        if definition:
            definition.validate_profile(self)
        elif self.default_atc_code is not None:
            raise ValidationError({"default_atc_code": "This planned form has no validated ATC schema. Leave this blank."})
        self.default_form_data = validate_form_data(form.definition_key, self.default_form_data)
        if self.default_atc_code is not None:
            checked = validate_form_data(form.definition_key, {"atc_code": self.default_atc_code})
            if "atc_code" in self.default_form_data and self.default_form_data["atc_code"] != checked["atc_code"]:
                raise ValidationError("The default ATC conflicts with default form data.")

    def __str__(self):
        return f"{self.client} / {self.form_definition}"
