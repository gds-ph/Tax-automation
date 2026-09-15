from django import forms
from django.core.exceptions import ValidationError
from .models import WorkOrder, ClientFilingProfile
from .services import EDITABLE_FIELDS
from automation_api.worker_policy import ENABLED_STATUSES


class WorkOrderForm(forms.Form):
    client_filing_profile = forms.ModelChoiceField(queryset=ClientFilingProfile.objects.none(), label="Client filing profile")
    filing_year = forms.RegexField(regex=r"\A[0-9]{4}\Z", max_length=4)
    filing_quarter = forms.TypedChoiceField(coerce=int, choices=[(q, f"Q{q}") for q in range(1, 5)])
    zero_filing = forms.BooleanField(required=False, label="This is a zero filing")
    zero_filing_approved = forms.BooleanField(required=False, label="I have reviewed and confirm this zero filing")
    atc_code = forms.CharField(required=False, label="ATC", help_text="Supply an ATC or use an explicitly configured profile default.")
    expected_version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.original_status = instance.status if instance else "DRAFT"
        profiles = ClientFilingProfile.objects.select_related("client", "form_definition")
        self.fields["client_filing_profile"].queryset = profiles.filter(is_active=True, client__is_active=True, form_definition__is_active=True,
            form_definition__definition_key="2551qv2018_zero")
        if instance:
            self.fields["client_filing_profile"].queryset = profiles.filter(pk=instance.client_filing_profile_id)
            self.fields["client_filing_profile"].disabled = True
            self.initial.update({name: getattr(instance, name) for name in EDITABLE_FIELDS})
            self.initial.update(client_filing_profile=instance.client_filing_profile_id, atc_code=instance.atc_code, expected_version=instance.version)
            self.fields["expected_version"].required = True
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs["class"] = "input"

    def clean(self):
        data = super().clean()
        if self.instance and self.instance.is_legacy_unlinked:
            raise ValidationError("This historical record must be explicitly linked and reviewed before editing.")
        if self.instance and data.get("expected_version") != self.instance.version:
            raise ValidationError("This work order changed. Reload before saving.")
        return data

    def source_data(self):
        data = {name: self.cleaned_data[name] for name in ("filing_year", "filing_quarter", "zero_filing", "zero_filing_approved")}
        atc = self.cleaned_data["atc_code"]
        data["form_data"] = {"atc_code": atc} if atc or self.instance else {}
        return data


class WorkOrderFilterForm(forms.Form):
    client = forms.CharField(required=False, max_length=200, label="Client", widget=forms.TextInput(attrs={"placeholder": "Name or client reference"}))
    status = forms.ChoiceField(required=False, choices=[("", "All statuses")] + [(key, label) for key, label in WorkOrder.Status.choices if key in ENABLED_STATUSES])
    year = forms.RegexField(regex=r"\A[0-9]{4}\Z", required=False, max_length=4, label="Year")
    quarter = forms.ChoiceField(required=False, choices=[("", "All quarters")] + [(str(q), f"Q{q}") for q in range(1, 5)])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"


class TransitionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
