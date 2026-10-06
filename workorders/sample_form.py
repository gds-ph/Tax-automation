"""Standalone draft layout preview; never creates or submits a filing."""
import json
import subprocess
from pathlib import Path
from django import forms
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.clickjacking import xframe_options_sameorigin
from .models import Client
from .contact_defaults import COMPANY_CONTACT
from .views import dashboard_permission

AMOUNTS = {
    14: 'Total Amount of Compensation',
    15: 'Statutory Minimum Wage for Minimum Wage Earners (MWEs)',
    16: 'Holiday Pay, Overtime Pay, Night Shift Differential Pay, Hazard Pay (for MWEs only)',
    17: '13th Month Pay and Other Benefits',
    18: 'De Minimis Benefits',
    19: "SSS, GSIS, PHIC, HDMF Mandatory Contributions & Union Dues (employee share only)",
    20: 'Other Non-Taxable Compensation',
    21: 'Total Non-Taxable Compensation (Sum of Items 15 to 20)',
    22: 'Total Taxable Compensation (Item 14 Less Item 21)',
    23: 'Taxable compensation not subject to withholding',
    24: 'Net Taxable Compensation (Item 22 Less Item 23)',
    25: 'Total Taxes Withheld',
    26: 'Adjustment of Taxes Withheld from Previous Months',
    27: 'Taxes Withheld for Remittance (Sum of Items 25 and 26)',
    28: 'Tax Remitted in Return Previously Filed, if this is an amended return',
    29: 'Other Remittances Made',
    30: 'Total Remittances Made (Sum of Items 28 and 29)',
    31: 'Tax Still Due / (Over-remittance) (Item 27 Less Item 30)',
}


class Sample1601CForm(forms.Form):
    month = forms.ChoiceField(label='1 For the month', choices=[(str(n), f'{n:02}') for n in range(1, 13)])
    year = forms.IntegerField(min_value=1900, max_value=2100, label='Year')
    amended = forms.ChoiceField(label='2 Amended return?', choices=[('No', 'No'), ('Yes', 'Yes')])
    withheld = forms.ChoiceField(label='3 Any taxes withheld?', choices=[('No', 'No'), ('Yes', 'Yes')])
    sheets = forms.IntegerField(label='4 Number of sheets attached', min_value=0, max_value=999, initial=0)
    atc = forms.CharField(label='5 ATC', max_length=12, initial='WW010')
    tin = forms.RegexField(r'^\d{3}-\d{3}-\d{3}-\d{5}$', label='6 Taxpayer Identification Number', help_text='000-000-000-00000')
    rdo = forms.RegexField(r'^[0-9A-Za-z]{3}$', label='7 RDO code')
    name = forms.CharField(label="8 Withholding agent’s name", max_length=200)
    address = forms.CharField(label='9 Registered address', max_length=500, widget=forms.Textarea(attrs={'rows': 2}))
    zip = forms.CharField(label='9A ZIP code', max_length=20)
    phone = forms.CharField(label='10 Contact number', max_length=50)
    category = forms.ChoiceField(label='11 Category of withholding agent', choices=[('Private', 'Private'), ('Government', 'Government')])
    email = forms.EmailField(label='12 Email address')
    relief = forms.ChoiceField(label='13 Availing of tax relief?', choices=[('No', 'No'), ('Yes', 'Yes')])
    relief_details = forms.CharField(label='13A If yes, specify', max_length=150, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for number, label in AMOUNTS.items():
            self.fields[f'amount_{number}'] = forms.DecimalField(label=f'{number} {label}', max_digits=15, decimal_places=2, initial=0)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'input'


@dashboard_permission('workorders.view_client')
@xframe_options_sameorigin
@require_http_methods(['GET', 'POST'])
def sample(request):
    today = timezone.localdate()
    initial = {'year': today.year, 'month': str(today.month), 'phone': COMPANY_CONTACT['telephone_number'],
               'email': COMPANY_CONTACT['email_address']}
    client = None
    if request.GET.get('client'):
        from django.http import Http404
        try:
            client_id = forms.UUIDField().clean(request.GET['client'])
        except forms.ValidationError:
            raise Http404('Company not found')
        client = get_object_or_404(Client, pk=client_id)
        initial.update(name=client.registered_name, address=client.registered_address,
                       tin=f'{client.tin1}-{client.tin2}-{client.tin3}-{client.tin4}', rdo=client.rdo_code, zip=client.zip_code)
    form = Sample1601CForm(request.POST if request.method == 'POST' else None, initial=initial)
    error = ''
    if request.method == 'POST' and form.is_valid():
        data = {key: str(value) for key, value in form.cleaned_data.items()}
        payload = {'data': data, 'amounts': AMOUNTS}
        try:
            result = subprocess.run(['node', str(Path(settings.BASE_DIR) / 'receipt_renderer' / 'sample-form.mjs')],
                                    input=json.dumps(payload).encode(), capture_output=True, timeout=30, check=True)
            if not result.stdout.startswith(b'%PDF'):
                raise ValueError('Invalid PDF output')
        except (OSError, subprocess.SubprocessError, ValueError):
            error = 'PDF generation is unavailable. Your entered values are retained below; try again.'
        else:
            response = HttpResponse(result.stdout, content_type='application/pdf')
            disposition = 'attachment' if request.POST.get('action') == 'download' else 'inline'
            response['Content-Disposition'] = f'{disposition}; filename="1601C-DRAFT-SAMPLE.pdf"'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
    return render(request, 'workorders/sample_form.html', {
        'section': 'sample', 'form': form, 'taxpayer': client,
        'clients': Client.objects.filter(is_active=True).order_by('registered_name'),
        'background_fields': [form[k] for k in list(form.fields) if not k.startswith('amount_')],
        'amount_fields': [form[f'amount_{n}'] for n in AMOUNTS], 'error': error,
    }, status=400 if request.method == 'POST' else 200)
