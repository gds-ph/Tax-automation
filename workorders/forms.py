from django import forms
from django.core.exceptions import ValidationError
from .models import Client, WorkOrder, ClientFilingProfile
from .services import EDITABLE_FIELDS
from automation_api.worker_policy import ENABLED_STATUSES


class ClientFilingCardsForm(forms.Form):
    filings = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    calendar_or_fiscal = forms.ChoiceField(required=False, choices=ClientFilingProfile.Basis.choices,
                                          label='Year basis for new cards')
    year_end_month = forms.ChoiceField(required=False, choices=[(f'{m:02}', f'{m:02}') for m in range(1, 13)],
                                      label='Year-end month for new cards')

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import FormDefinition
        self.existing = list(client.filing_profiles.select_related('form_definition').order_by('form_definition__form_code'))
        self.available = list(FormDefinition.objects.filter(is_active=True).exclude(
            pk__in=[p.form_definition_id for p in self.existing]).order_by('form_code', 'form_version'))
        self.fields['filings'].choices = [(str(f.pk), f'{f.form_code} — {f.display_name}') for f in self.available]
        self.initial.setdefault('calendar_or_fiscal', self.existing[0].calendar_or_fiscal if self.existing else 'CALENDAR')
        self.initial.setdefault('year_end_month', self.existing[0].year_end_month if self.existing else '12')
        for name in ('calendar_or_fiscal', 'year_end_month'):
            self.fields[name].widget.attrs['class'] = 'input'

    @property
    def filing_options(self):
        frequencies = {str(f.pk): f.filing_frequency for f in self.available}
        return [(frequencies[o.data['value']], o) for o in self['filings']]

    def clean(self):
        data = super().clean()
        if data.get('filings'):
            for field in ('calendar_or_fiscal', 'year_end_month'):
                if not data.get(field):
                    self.add_error(field, 'Choose this setting for the new filing cards.')
            if data.get('calendar_or_fiscal') == 'CALENDAR' and data.get('year_end_month') != '12':
                self.add_error('year_end_month', 'Calendar years end in December (12).')
        return data


class ClientForm(forms.ModelForm):
    """Edits the reusable client record through the audited catalog service.

    Client folder path is deliberately absent: it is automation-VM metadata, not
    a taxpayer detail reviewed on this screen.
    """
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = Client
        fields = ('registered_name', 'trade_name', 'client_type', 'tin1', 'tin2', 'tin3', 'tin4',
                  'rdo_code', 'registered_address', 'zip_code', 'telephone_number', 'email_address', 'rdo_email',
                  'line_of_business', 'client_code', 'is_active')
        labels = {'tin1': 'TIN — first 3 digits', 'tin2': 'TIN — next 3 digits',
                  'tin3': 'TIN — last 3 digits', 'tin4': 'Branch code — 5 digits',
                  'rdo_code': 'RDO code', 'client_type': 'Taxpayer type',
                  'client_code': 'Client reference', 'is_active': 'Active'}
        help_texts = {
            'rdo_email': 'Optional contact email for the company’s Revenue District Office.',
            'client_code': 'Used as the client reference on new filings. Existing work-order snapshots keep the reference they were prepared with.',
            'trade_name': 'Optional. Shown in place of the registered name when present.',
            'tin4': 'Leading zeros are significant and are never added automatically.',
        }
        widgets = {'registered_address': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .contact_defaults import contact_for_client
        for name, value in contact_for_client(self.instance.client_code).items():
            self.initial[name] = value
            self.fields[name].disabled = True
            self.fields[name].help_text = 'Contact used for new filings for this client.'

        self.fields['expected_version'].initial = self.instance.version
        self.fields['telephone_number'].required = False
        self.fields['email_address'].required = False
        self.fields['trade_name'].required = False
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs['class'] = 'input'

    def clean(self):
        data = super().clean()
        if data.get('expected_version') != self.instance.version:
            raise ValidationError('This client changed. Reload before saving.')
        names = ('tin1', 'tin2', 'tin3', 'tin4')
        segments = [data.get(name) for name in names]
        # Mirrors the COR setup guard, but only for a TIN actually being changed:
        # nothing here should block an address fix on a pre-existing duplicate.
        changed = all(segments) and segments != [self.initial.get(name) for name in names]
        if changed and Client.objects.filter(
                **dict(zip(names, segments))).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Another client already uses this TIN and branch code. Reconcile the two records instead of creating a duplicate.')
        return data

    def changes(self):
        return {name: self.cleaned_data[name] for name in self.Meta.fields}


class WorkOrderForm(forms.Form):
    client_filing_profile = forms.ModelChoiceField(queryset=ClientFilingProfile.objects.none(), label="Client filing profile")
    filing_year = forms.RegexField(regex=r"\A[0-9]{4}\Z", max_length=4)
    filing_quarter = forms.TypedChoiceField(coerce=int, choices=[(q, f"Q{q}") for q in range(1, 5)])
    filing_month = forms.TypedChoiceField(coerce=int, choices=[(m, f'{m:02d}') for m in range(1, 13)])
    zero_filing = forms.BooleanField(required=False, label="This is a zero filing")
    zero_filing_approved = forms.BooleanField(required=False, label="I have reviewed and confirm this zero filing")
    atc_code = forms.CharField(required=False, label="ATC", help_text="Supply an ATC or use an explicitly configured profile default.")
    expected_version = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.original_status = instance.status if instance else "DRAFT"
        self.monthly = bool(instance and instance.filing_month is not None)
        self.fields.pop('filing_quarter' if self.monthly else 'filing_month')
        if self.monthly:
            self.fields.pop('atc_code')
            self.fields['zero_filing_approved'].label = 'I confirm a private agent with no compensation, withholding, attachments, tax relief or prior-month adjustments.'
        if instance and instance.expected_form_number == '1601EQ':
            self.fields.pop('atc_code', None)
            self.fields['zero_filing_approved'].label = 'I confirm a non-amended private-agent return with no withholding, remittances, credits, penalties or attachments.'
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
        data = {name: self.cleaned_data[name] for name in ("filing_year", 'filing_month' if self.monthly else 'filing_quarter', "zero_filing", "zero_filing_approved")}
        if self.monthly or (self.instance and self.instance.expected_form_number == '1601EQ'):
            data['form_data'] = {}
            return data
        atc = self.cleaned_data["atc_code"]
        data["form_data"] = {"atc_code": atc} if atc or self.instance else {}
        return data


class WorkOrderFilterForm(forms.Form):
    client = forms.CharField(required=False, max_length=200, label="Client", widget=forms.TextInput(attrs={"placeholder": "Name or client reference"}))
    status = forms.ChoiceField(required=False, choices=[("", "All statuses")] + [(key, label) for key, label in WorkOrder.Status.choices if key in ENABLED_STATUSES])
    year = forms.RegexField(regex=r"\A[0-9]{4}\Z", required=False, max_length=4, label="Year")
    quarter = forms.ChoiceField(required=False, choices=[("", "All quarters")] + [(str(q), f"Q{q}") for q in range(1, 5)])
    month = forms.ChoiceField(required=False, choices=[('', 'All months')] + [(str(m), f'{m:02d}') for m in range(1, 13)])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"


class TransitionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
