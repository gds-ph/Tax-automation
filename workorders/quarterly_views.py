import calendar
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from .models import ClientFilingProfile, ExpandedWithholdingDraft
from .quarterly_models import QuarterlyWithholdingDraft, QuarterlyWithholdingRevision
from .quarterly_withholding import calculate
from .atc_catalog import ATC_ENTRIES
from .period_policy import default_completed_period
from .views import dashboard_permission

SALT = '1601eq-draft-review-v1'


class PeriodForm(forms.Form):
    year = forms.IntegerField(min_value=2000, max_value=9998)
    quarter = forms.TypedChoiceField(coerce=int, choices=[(q, f'Quarter {q}') for q in range(1, 5)])


class AmountForm(forms.Form):
    first_remittance = forms.CharField(initial='0.00', max_length=24, label='20 · Paid for first month (₱)')
    second_remittance = forms.CharField(initial='0.00', max_length=24, label='21 · Paid for second month (₱)')

    surcharge = forms.CharField(required=False, initial='0.00', max_length=24, label='26 · Surcharge (₱)')
    interest = forms.CharField(required=False, initial='0.00', max_length=24, label='27 · Interest (₱)')
    compromise = forms.CharField(required=False, initial='0.00', max_length=24, label='28 · Compromise (₱)')

class RowForm(forms.Form):
    month = forms.TypedChoiceField(coerce=int, choices=[(m, calendar.month_abbr[m]) for m in range(1, 13)])
    payee = forms.CharField(max_length=200)
    tin = forms.CharField(max_length=17)
    atc = forms.CharField(max_length=5, widget=forms.TextInput(attrs={'list': 'eq-atcs', 'autocomplete': 'off'}))
    base = forms.CharField(max_length=24)
    reference = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['aria-label'] = name.replace('_', ' ').title()


Rows = forms.formset_factory(RowForm, extra=0, can_delete=True, max_num=500, validate_max=True, absolute_max=500)


@dashboard_permission('workorders.view_client', 'workorders.view_clientfilingprofile',
                      'workorders.view_workorder', 'workorders.add_workorder', 'workorders.change_workorder')
@require_http_methods(['GET', 'POST'])
def worksheet(request, pk, profile_pk):
    profile = get_object_or_404(ClientFilingProfile.objects.select_related('client', 'form_definition'),
        pk=profile_pk, client_id=pk, is_active=True, client__is_active=True,
        form_definition__definition_key='cor_1601eq', form_definition__is_active=True)
    defaults = default_completed_period('QUARTERLY')
    period = PeriodForm(request.POST if request.method == 'POST' else request.GET or
                        {'year': defaults['filing_year'], 'quarter': defaults['filing_quarter']})
    preview = None
    token = error = ''
    status = 200
    draft = None
    data = {}
    year, quarter = int(defaults['filing_year']), defaults['filing_quarter']
    if period.is_valid():
        year, quarter = period.cleaned_data['year'], period.cleaned_data['quarter']
        draft = QuarterlyWithholdingDraft.objects.filter(client_id=pk, year=year, quarter=quarter).first()
        data = draft.data if draft else {}
    rows = Rows(initial=data.get('rows') or [{'month': quarter * 3 - 2}], prefix='rows')
    monthly_drafts = list(ExpandedWithholdingDraft.objects.filter(client_id=pk, year=year,
        month__in=[quarter * 3 - 2, quarter * 3 - 1]).order_by('month')) if period.is_valid() else []
    monthly_totals = {monthly.month: f'{monthly.total:.2f}' for monthly in monthly_drafts}
    suggested = {'first_remittance': monthly_totals.get(quarter * 3 - 2, '0.00'),
                 'second_remittance': monthly_totals.get(quarter * 3 - 1, '0.00')}
    # Saved edits take precedence over suggestions from monthly drafts.
    amounts = AmountForm(initial={**suggested, **data})
    action = request.POST.get('action')
    if request.method == 'POST':
        try:
            if not period.is_valid():
                raise ValidationError('Choose a valid year and quarter.')
            if action == 'load-months':
                initial = []
                for monthly in monthly_drafts:
                    initial.extend([{**r, 'month': monthly.month} for r in monthly.rows])
                if len(initial) > 500:
                    raise ValidationError('Monthly drafts exceed the 500 transaction limit.')
                rows = Rows(initial=initial or [{'month': quarter * 3 - 2}], prefix='rows')
                # Editable suggestions, not verified payment records. Preserve saved overrides.
                amounts = AmountForm(initial={**suggested, **data})
            elif action == 'preview':
                rows = Rows(request.POST, prefix='rows')
                amounts = AmountForm(request.POST)
                if not (rows.is_valid() and amounts.is_valid()):
                    raise ValidationError('Correct the transaction and remittance entries.')
                preview = calculate([r for r in rows.cleaned_data if r and not r.get('DELETE')], quarter,
                                    **amounts.cleaned_data)
                version = int(request.POST.get('version', '0'))
                if version != (draft.version if draft else 0):
                    raise ValidationError('This draft changed in another tab. Reload before editing.')
                token = signing.dumps({'actor': request.user.pk, 'profile': str(profile.pk), 'year': year,
                    'quarter': quarter, 'version': version, 'data': preview,
                    'client_version': profile.client.version}, salt=SALT, compress=True)
            elif action == 'save':
                if request.POST.get('reviewed') != 'on':
                    raise ValidationError('Confirm the quarterly schedule before saving.')
                signed = signing.loads(request.POST.get('token', ''), salt=SALT, max_age=1800)
                if (signed['actor'] != request.user.pk or signed['profile'] != str(profile.pk)
                    or signed['year'] != year or signed['quarter'] != quarter
                    or signed['client_version'] != profile.client.version):
                    raise ValidationError('The client or period changed. Review again.')
                checked = calculate(signed['data']['rows'], quarter, signed['data']['first_remittance'], signed['data']['second_remittance'], **{key: signed['data'].get(key, '0') for key in ('surcharge', 'interest', 'compromise')})
                with transaction.atomic():
                    current = QuarterlyWithholdingDraft.objects.select_for_update().filter(client_id=pk, year=year, quarter=quarter).first()
                    if (current.version if current else 0) != signed['version']:
                        raise ValidationError('The draft changed or this review was already saved. Reload before editing.')
                    if current:
                        current.data = checked
                        current.version += 1
                        current.save()
                    else:
                        current = QuarterlyWithholdingDraft.objects.create(client_id=pk, year=year, quarter=quarter, data=checked)
                    QuarterlyWithholdingRevision.objects.create(draft=current, version=current.version, data=checked, actor=request.user)
                return redirect(reverse('workorders:quarterly-worksheet', args=[pk, profile_pk]) + f'?year={year}&quarter={quarter}&saved=1')
            else:
                raise ValidationError('Unknown worksheet action.')
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            error, status = 'Review expired or invalid. Reload and review again.', 400
        except (ValidationError, IntegrityError) as exc:
            error, status = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'The draft changed. Reload and try again.', 409
    return render(request, 'workorders/quarterly_worksheet.html', {'profile': profile, 'taxpayer': profile.client,
        'period': period, 'year': year, 'quarter': quarter, 'rows': rows, 'amounts': amounts,
        'preview': preview, 'token': token, 'draft': draft, 'error': error, 'atcs': ATC_ENTRIES,
        'loaded': action == 'load-months', 'section': 'clients'}, status=status)
