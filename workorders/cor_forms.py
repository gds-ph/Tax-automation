from django import forms
from .catalog_models import Client
from .cor_extraction import FORM_CATALOG

TAXPAYER_FIELDS = ('registered_name', 'client_type', 'tin1', 'tin2', 'tin3', 'tin4',
                   'rdo_code', 'registered_address', 'zip_code', 'telephone_number',
                   'email_address', 'line_of_business')


class CORReviewForm(forms.Form):
    registered_name = forms.CharField(max_length=200)
    client_type = forms.ChoiceField(choices=[('', 'Choose taxpayer type')] + list(Client.Type.choices))
    tin1 = forms.RegexField(r'\A[0-9]{3}\Z', label='TIN — first 3 digits')
    tin2 = forms.RegexField(r'\A[0-9]{3}\Z', label='TIN — next 3 digits')
    tin3 = forms.RegexField(r'\A[0-9]{3}\Z', label='TIN — last 3 digits')
    tin4 = forms.RegexField(r'\A[0-9]{5}\Z', label='Branch code — 5 digits')
    rdo_code = forms.RegexField(r'\A[0-9A-Za-z]{3}\Z', label='RDO code')
    registered_address = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={'rows': 3}))
    zip_code = forms.CharField(max_length=20)
    telephone_number = forms.CharField(max_length=50, required=False, label='Telephone number (optional)')
    email_address = forms.EmailField(required=False, label='Email address (optional)')
    line_of_business = forms.CharField(max_length=200)
    year_end_month = forms.ChoiceField(choices=[('', 'Confirm year-end month')] + [(f'{n:02}', f'{n:02}') for n in range(1, 13)])
    calendar_or_fiscal = forms.ChoiceField(choices=[('', 'Choose year basis'), ('CALENDAR', 'Calendar'), ('FISCAL', 'Fiscal')])
    filings = forms.MultipleChoiceField(choices=[(c, f'{c} — {v[0]} ({v[1].title()})') for c, v in FORM_CATALOG.items()], widget=forms.CheckboxSelectMultiple)
    confirmed = forms.BooleanField(label='I checked the source document, taxpayer details and current filing requirements, and approve this setup.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in {'filings', 'confirmed'}:
                field.widget.attrs['class'] = 'input'

    def clean(self):
        data = super().clean()
        selected = set(data.get('filings', []))
        if {'1701', '1701A'} <= selected:
            self.add_error('filings', 'Select the applicable annual income tax form, not both alternatives.')
        if {'2550Q', '2551Q'} <= selected:
            self.add_error('filings', 'VAT and percentage-tax entries need separate registration review. Select the currently applicable form.')
        if data.get('calendar_or_fiscal') == 'CALENDAR' and data.get('year_end_month') != '12':
            self.add_error('year_end_month', 'Calendar years end in December (12).')
        return data
