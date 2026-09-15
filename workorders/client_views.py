"""Client-first navigation; creates local queue entries, never launches PAD."""
import uuid
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import OperationalError, IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.utils import timezone
from .models import Client, ClientFilingProfile
from .definitions import get_definition
from .views import dashboard_permission, _add_errors
from . import services


class PreparationForm(forms.Form):
    filing_year = forms.RegexField(regex=r'\A[0-9]{4}\Z', max_length=4, label='Year')
    filing_quarter = forms.TypedChoiceField(coerce=int, choices=[('', 'Choose a quarter')] + [(q, f'Quarter {q}') for q in range(1, 5)], label='Quarter')
    zero_filing_approved = forms.BooleanField(label='I have checked the details and confirm this is a zero filing.')
    request_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs['class'] = 'input'


def available(profile):
    form = profile.form_definition
    return bool(profile.is_active and profile.client.is_active and form.is_active
                and form.preparation_automation_available and get_definition(form.definition_key))


@dashboard_permission('workorders.view_client')
@require_GET
def client_list(request):
    from . import client_directory
    query = request.GET.get('q', '').strip()[:200]
    clients = Client.objects.filter(is_active=True)
    if query:
        clients = clients.filter(Q(registered_name__icontains=query) | Q(trade_name__icontains=query) | Q(client_code__icontains=query) | Q(registration_setup__folder__icontains=query))
    entries = list(clients)
    error = ''
    try:
        from .models import RegistrationSetup
        linked = set(RegistrationSetup.objects.values_list('folder', flat=True))
        entries.extend({'display_name': name, 'directory_entry': True} for name in client_directory.names()
                       if name not in linked and (not query or query.casefold() in name.casefold()))
    except client_directory.DirectoryUnavailable as exc:
        error = str(exc)
    entries.sort(key=lambda entry: (entry['display_name'] if isinstance(entry, dict) else entry.display_name).casefold())
    page = Paginator(entries, 20).get_page(request.GET.get('page'))
    return render(request, 'workorders/clients.html', {'page_obj': page, 'query': query, 'section': 'clients', 'directory_error': error})


@dashboard_permission('workorders.view_client', 'workorders.view_clientfilingprofile', 'workorders.view_formdefinition')
@require_GET
def client_detail(request, pk):
    from .demo_reset import is_reset_demo
    client = get_object_or_404(Client, pk=pk)
    profiles = client.filing_profiles.filter(is_active=True, form_definition__is_active=True).select_related('client', 'form_definition').order_by('-form_definition__preparation_automation_available', 'form_definition__form_code')
    for profile in profiles:
        profile.can_prepare = available(profile)
    orders = client.work_orders.filter(is_archived=False)[:10] if request.user.has_perm('workorders.view_workorder') else []
    return render(request, 'workorders/client_detail.html', {'taxpayer': client, 'profiles': profiles, 'orders': orders, 'section': 'clients', 'can_reset_demo': request.user.is_superuser and is_reset_demo(client)})


@dashboard_permission('workorders.view_client', 'workorders.view_clientfilingprofile', 'workorders.view_formdefinition',
                      'workorders.view_workorder', 'workorders.add_workorder', 'workorders.change_workorder')
@require_http_methods(['GET', 'POST'])
def prepare(request, pk, profile_pk):
    profile = get_object_or_404(ClientFilingProfile.objects.select_related('client', 'form_definition'), pk=profile_pk, client_id=pk)
    if not available(profile):
        return render(request, 'workorders/preparation_unavailable.html', {'taxpayer': profile.client, 'section': 'clients'}, status=409)
    versions = {'client': profile.client.version, 'form': profile.form_definition.version, 'profile': profile.version}
    today = timezone.localdate()
    initial = {'filing_year': str(today.year),
               'filing_quarter': (today.month - 1) // 3 + 1,
               'request_token': signing.dumps({'actor': request.user.pk, 'profile': str(profile.pk), 'request': str(uuid.uuid4()), 'versions': versions}, salt='client-preparation')}
    form = PreparationForm(request.POST if request.method == 'POST' else None, initial=initial)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            token = signing.loads(form.cleaned_data['request_token'], salt='client-preparation', max_age=3600)
            if token['actor'] != request.user.pk or token['profile'] != str(profile.pk):
                raise ValidationError('This request belongs to another client or filing. Reload this page.')
            data = {name: form.cleaned_data[name] for name in ('filing_year', 'filing_quarter', 'zero_filing_approved')}
            data.update(zero_filing=True, form_data={'atc_code': profile.default_atc_code or profile.default_form_data.get('atc_code') or 'PT 010'})
            order = services.create_and_queue_work_order(actor=request.user, data=data, client_filing_profile_id=profile.pk,
                        request_id=uuid.UUID(token['request']), source_versions=token['versions'])
        except signing.BadSignature:
            form.add_error(None, 'This page has expired. Reload and review the filing again.')
            status = 400
        except ValidationError as error:
            _add_errors(form, error)
            status = 409
        except (OperationalError, IntegrityError):
            form.add_error(None, 'Another request is being saved. Retry this same form shortly; it will not queue twice.')
            status = 409
        else:
            messages.success(request, 'Task queued. Waiting for the VM worker.' if order.status == 'READY_TO_PREPARE' else 'This request was already saved. Showing its current status.')
            return redirect('workorders:detail', pk=order.pk)
    return render(request, 'workorders/prepare.html', {'taxpayer': profile.client, 'profile': profile, 'form': form, 'section': 'clients'}, status=status)
