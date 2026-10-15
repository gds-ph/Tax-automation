import uuid
from calendar import month_name
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from .models import ClientFilingProfile
from .views import dashboard_permission
from .client_views import available
from .period_policy import default_completed_period, validate_completed_period
from .payroll_1601c import FIELDS, normalize, totals
from .services import create_and_queue_work_order

SALT = '1601c-payroll-review-v1'


class PayrollForm(forms.Form):
    filing_year = forms.RegexField(regex=r'\A[0-9]{4}\Z', label='Year')
    filing_month = forms.TypedChoiceField(coerce=int, choices=[(m, month_name[m]) for m in range(1, 13)], label='Month')
    other_exempt_description = forms.CharField(max_length=25, required=False, label='Description of other non-taxable compensation')
    scope = forms.BooleanField(label='I confirm an original private-employer return, with no prior-month adjustments, remittance credits, tax relief, required attachments or penalties. Payroll has already calculated the withholding.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, label in FIELDS:
            self.fields[key] = forms.DecimalField(label=label, min_value=0, max_digits=13, decimal_places=2, initial='0.00')
        self.order_fields(['filing_year', 'filing_month'] + [key for key, _ in FIELDS] + ['other_exempt_description', 'scope'])
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'input'})

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        validate_completed_period('MONTHLY', data['filing_year'], data['filing_month'])
        self.payroll = normalize({**{key: format(data[key], '.2f') for key, _ in FIELDS},
            'schema': '1601c-payroll-v1', 'payroll_confirmed': True,
            'other_exempt_description': data['other_exempt_description']})
        return data


@dashboard_permission('workorders.view_client', 'workorders.view_clientfilingprofile', 'workorders.view_formdefinition',
                      'workorders.view_workorder', 'workorders.add_workorder', 'workorders.change_workorder')
@require_http_methods(['GET', 'POST'])
def prepare(request, pk, profile_pk):
    profile = get_object_or_404(ClientFilingProfile.objects.select_related('client', 'form_definition'),
                               pk=profile_pk, client_id=pk, form_definition__definition_key='1601cv2018_zero')
    if not available(profile):
        return render(request, 'workorders/preparation_unavailable.html', {'taxpayer': profile.client}, status=409)
    versions = {'client': profile.client.version, 'form': profile.form_definition.version, 'profile': profile.version}
    form = PayrollForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'preview' else None,
                       initial=default_completed_period('MONTHLY'))
    preview = None
    token = ''
    error = ''
    status = 200
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'queue':
                if request.POST.get('reviewed') != 'on':
                    raise ValidationError('Confirm the reviewed payroll summary before queuing.')
                data = signing.loads(request.POST.get('preview_token', ''), salt=SALT, max_age=1800)
                if data['actor'] != request.user.pk or data['profile'] != str(profile.pk) or data['versions'] != versions:
                    raise ValidationError('Client or filing settings changed. Review the payroll again.')
                payroll = normalize(data['payroll'])
                order = create_and_queue_work_order(actor=request.user, client_filing_profile_id=profile.pk,
                    request_id=uuid.UUID(data['request']), source_versions=versions,
                    data={'filing_year': data['year'], 'filing_month': data['month'], 'zero_filing': False,
                          'zero_filing_approved': False, 'form_data': payroll})
                return redirect('workorders:detail', pk=order.pk)
            elif request.POST.get('action') == 'preview' and form.is_valid():
                preview = form.payroll
                token = signing.dumps({'actor': request.user.pk, 'profile': str(profile.pk), 'versions': versions,
                    'request': str(uuid.uuid4()), 'year': form.cleaned_data['filing_year'],
                    'month': form.cleaned_data['filing_month'], 'payroll': preview}, salt=SALT, compress=True)
            else:
                status = 400
        except signing.BadSignature:
            error = 'Review expired or invalid. Preview the payroll again.'
            status = 400
        except ValidationError as exc:
            error = ' '.join(exc.messages)
            status = 409
    return render(request, 'workorders/payroll_prepare.html', {'form': form, 'profile': profile,
        'taxpayer': profile.client, 'preview': preview, 'totals': totals(preview) if preview else None,
        'preview_token': token, 'error': error, 'section': 'clients'}, status=status)
