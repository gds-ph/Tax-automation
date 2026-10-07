"""Client-first navigation; creates local queue entries, never launches PAD."""
import uuid
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import OperationalError, IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils import timezone
from .models import Client, ClientFilingProfile
from .definitions import get_definition
from .views import dashboard_permission, _add_errors
from . import services


class PreparationForm(forms.Form):
    filing_mode = forms.ChoiceField(choices=[('ZERO', 'Zero filing'), ('NONZERO', 'Non-zero filing')], initial='ZERO', label='Filing type')
    filing_year = forms.RegexField(regex=r'\A[0-9]{4}\Z', max_length=4, label='Year')
    filing_quarter = forms.TypedChoiceField(coerce=int, choices=[('', 'Choose a quarter')] + [(q, f'Quarter {q}') for q in range(1, 5)], label='Quarter')
    filing_month = forms.TypedChoiceField(coerce=int, choices=[('', 'Choose a month')] + [(m, f'{m:02d}') for m in range(1, 13)], label='Month')
    zero_filing_approved = forms.BooleanField(required=False, label='I have checked the details and confirm this is a zero filing.')
    request_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, frequency='QUARTERLY', form_code='', **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('filing_quarter' if frequency == 'MONTHLY' else 'filing_month')
        if frequency == 'MONTHLY':
            self.fields['zero_filing_approved'].label = ('I confirm this is a private withholding agent with no compensation, withholding, attachments, tax relief or prior-month adjustments for this month.')
        if form_code == '1600VT':
            self.fields['zero_filing_approved'].label = 'I confirm a non-amended private-agent 1600-VT return with no tax withheld, attachments, tax relief, credits or penalties.'
        if form_code == '0619F':
            self.fields['zero_filing_approved'].label = 'I confirm a non-amended private-agent 0619-F return with no final income tax withheld, remittance or penalties.'
        if form_code == '1601EQ':
            self.fields['zero_filing_approved'].label = 'I confirm a non-amended private-agent return with no withholding, remittances, credits, penalties or attachments.'
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs['class'] = 'input'

    def clean(self):
        data = super().clean()
        if data.get('filing_mode') == 'NONZERO':
            self.add_error('filing_mode', 'Non-zero filing automation is not yet available. No task has been queued.')
        elif data.get('filing_mode') == 'ZERO' and not data.get('zero_filing_approved'):
            self.add_error('zero_filing_approved', 'Confirm that this is a zero filing.')
        return data


def available(profile):
    form = profile.form_definition
    return bool(profile.is_active and profile.client.is_active and form.is_active
                and form.preparation_automation_available and get_definition(form.definition_key))


# Client-page views. Filing cards stay the landing tab: preparing a filing is the
# reason this page is opened.
CLIENT_TABS = {'details': 'Company details', 'filings': 'Filing cards', 'history': 'History'}
DEFAULT_CLIENT_TAB = 'filings'


def tab_url(request, value):
    """Keep unrelated query parameters when switching tabs."""
    params = request.GET.copy()
    params['tab'] = value
    return f'{request.path}?{params.urlencode()}'


def saved_targets(user):
    """A user's saved clients and folders, with folders that since became clients
    resolved to those clients so a reviewed setup never drops out of the list."""
    from .models import RegistrationSetup, SavedCompany
    saved = list(SavedCompany.objects.filter(user=user))
    client_ids = {row.client_id for row in saved if row.client_id}
    folders = {row.folder for row in saved if row.folder}
    if folders:
        for folder, client_id in RegistrationSetup.objects.filter(folder__in=folders).values_list('folder', 'client_id'):
            client_ids.add(client_id)
            folders.discard(folder)
    return client_ids, folders


@dashboard_permission('workorders.view_client')
@require_POST
def saved_toggle(request):
    """Adds or removes one saved company for the signed-in user only."""
    from .models import RegistrationSetup, SavedCompany
    client_id = request.POST.get('client', '').strip()
    folder = request.POST.get('folder', '').strip()[:500]
    if bool(client_id) == bool(folder):
        raise Http404('Choose one company to save.')
    if client_id:
        target = {'client': get_object_or_404(Client, pk=client_id)}
    else:
        # Saving a reviewed folder records its client, so the two never diverge.
        setup = RegistrationSetup.objects.filter(folder=folder).first()
        target = {'client': setup.client} if setup else {'folder': folder}
    existing = SavedCompany.objects.filter(user=request.user, **target).first()
    if existing:
        existing.delete()
    else:
        SavedCompany.objects.create(user=request.user, **target)
    params = {name: request.POST.get(name, '') for name in ('q', 'form', 'tab', 'page')}
    params = {name: value for name, value in params.items() if value}
    # Rebuilt from known parameters only; never redirects to a supplied URL.
    return redirect(f"{reverse('workorders:clients')}?{urlencode(params)}" if params else 'workorders:clients')


@dashboard_permission('workorders.view_client')
@require_GET
def client_list(request):
    from . import client_directory
    from .models import SavedCompany
    query = request.GET.get('q', '').strip()[:200]
    form_query = request.GET.get('form', '').strip()[:100]
    saved_client_ids, saved_folders = saved_targets(request.user)
    has_saved = bool(saved_client_ids or saved_folders)
    tab = request.GET.get('tab', '')
    tab = tab if tab in {'saved', 'all'} else ('saved' if has_saved else 'all')
    clients = Client.objects.filter(is_active=True)
    matching_folders = set()
    if form_query:
        from .models import RegistrationCardScan
        from .cor_selection import select_documents
        from .cor_extraction import FORM_CATALOG
        needle = form_query.casefold()
        clients = clients.filter(
            filing_profiles__is_active=True, filing_profiles__form_definition__is_active=True,
        ).filter(Q(filing_profiles__form_definition__form_code__icontains=form_query)
                 | Q(filing_profiles__form_definition__display_name__icontains=form_query)).distinct()
        for scan in RegistrationCardScan.objects.exclude(documents=[]).iterator():
            documents, _ = select_documents(scan)
            if any(needle in (row.get('form_code', '') + ' ' +
                       FORM_CATALOG.get(row.get('form_code', '').strip().upper(),
                                        (row.get('tax_type', ''), ''))[0]).casefold()
                   for document in documents for row in document['result']['rows']):
                matching_folders.add(scan.folder)
    if query:
        clients = clients.filter(Q(registered_name__icontains=query) | Q(trade_name__icontains=query) | Q(client_code__icontains=query) | Q(registration_setup__folder__icontains=query))
    if tab == 'saved':
        clients = clients.filter(pk__in=saved_client_ids)
    entries = list(clients)
    for taxpayer in entries:
        taxpayer.is_saved = taxpayer.pk in saved_client_ids
    error = ''
    folder_names = []
    try:
        from .models import RegistrationSetup
        linked = set(RegistrationSetup.objects.values_list('folder', flat=True))
        folder_names = [name for name in client_directory.names()
                        if name not in linked and (not query or query.casefold() in name.casefold())
                        and (not form_query or name in matching_folders)]
    except client_directory.DirectoryUnavailable as exc:
        error = str(exc)
        # Saved folders are known by name, so the saved list still works offline.
        if tab == 'saved':
            folder_names = sorted(saved_folders)
            error = ''
    if tab == 'saved':
        folder_names = [name for name in folder_names if name in saved_folders]
    entries.extend({'display_name': name, 'directory_entry': True, 'is_saved': name in saved_folders}
                   for name in folder_names)
    entries.sort(key=lambda entry: (entry['display_name'] if isinstance(entry, dict) else entry.display_name).casefold())
    page = Paginator(entries, 20).get_page(request.GET.get('page'))
    return render(request, 'workorders/clients.html', {
        'page_obj': page, 'query': query, 'form_query': form_query, 'section': 'clients',
        'directory_error': error, 'tab': tab, 'has_saved': has_saved,
        'saved_count': SavedCompany.objects.filter(user=request.user).count()})


@dashboard_permission('workorders.view_client', 'workorders.view_clientfilingprofile', 'workorders.view_formdefinition')
@require_GET
def client_detail(request, pk):
    from .demo_reset import is_reset_demo
    client = get_object_or_404(Client, pk=pk)
    profiles = client.filing_profiles.filter(is_active=True, form_definition__is_active=True).select_related('client', 'form_definition').order_by('-form_definition__preparation_automation_available', 'form_definition__form_code')
    for profile in profiles:
        profile.can_prepare = available(profile)
    history = client.work_orders.filter(is_archived=False) if request.user.has_perm('workorders.view_workorder') else client.work_orders.none()
    tab = request.GET.get('tab', '')
    tab = tab if tab in CLIENT_TABS else DEFAULT_CLIENT_TAB
    return render(request, 'workorders/client_detail.html', {
        'taxpayer': client, 'profiles': profiles, 'orders': history[:25],
        'order_count': history.count(), 'profile_count': len(profiles),
        'tab': tab, 'tab_label': CLIENT_TABS[tab],
        'tabs': [(value, label, tab_url(request, value)) for value, label in CLIENT_TABS.items()],
        'section': 'clients', 'can_reset_demo': request.user.is_superuser and is_reset_demo(client)})


@dashboard_permission('workorders.view_client', 'workorders.change_client')
@require_http_methods(['GET', 'POST'])
def client_edit(request, pk):
    from .catalog_services import update_record, create_record
    from .forms import ClientForm, ClientFilingCardsForm
    from django.db import transaction
    from django.core.exceptions import PermissionDenied
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST if request.method == 'POST' else None, instance=client)
    can_add_cards = request.user.has_perm('workorders.add_clientfilingprofile')
    cards = ClientFilingCardsForm(request.POST if request.method == 'POST' else None, client=client, prefix='cards')
    if request.method == 'POST' and request.POST.getlist('cards-filings') and not can_add_cards:
        raise PermissionDenied('Adding filing cards requires filing-profile creation permission.')
    status = 200
    # A queued order is matched against the snapshot it was reviewed with, so
    # changing the client here stops the worker claiming it until it is refreshed.
    queued = client.work_orders.filter(is_archived=False, status__in=('READY_TO_PREPARE', 'DRAFT')).count()
    if request.method == 'POST' and form.is_valid() and cards.is_valid():
        try:
            with transaction.atomic():
                saved = update_record(model=Client, pk=client.pk, actor=request.user,
                                      expected_version=form.cleaned_data['expected_version'], changes=form.changes())
                selected = set(cards.cleaned_data['filings'])
                for definition in cards.available:
                    if str(definition.pk) in selected:
                        create_record(model=ClientFilingProfile, actor=request.user, data={
                            'client': saved, 'form_definition': definition,
                            'calendar_or_fiscal': cards.cleaned_data['calendar_or_fiscal'],
                            'year_end_month': cards.cleaned_data['year_end_month']})
        except ValidationError as error:
            _add_errors(form, error)
            status = 409
        except (OperationalError, IntegrityError):
            form.add_error(None, 'Another update is in progress. Reload this client and try again.')
            status = 409
        else:
            messages.success(request, 'Client details and selected filing cards saved.')
            return redirect(f"{reverse('workorders:client-detail', args=[client.pk])}?tab=details")
    return render(request, 'workorders/client_form.html',
                  {'taxpayer': client, 'form': form, 'cards': cards, 'can_add_cards': can_add_cards, 'queued': queued, 'section': 'clients'}, status=status)


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
               'filing_month': today.month,
               'filing_quarter': (today.month - 1) // 3 + 1,
               'request_token': signing.dumps({'actor': request.user.pk, 'profile': str(profile.pk), 'request': str(uuid.uuid4()), 'versions': versions}, salt='client-preparation')}
    monthly = profile.form_definition.filing_frequency == 'MONTHLY'
    form = PreparationForm(request.POST if request.method == 'POST' else None, initial=initial,
                           frequency=profile.form_definition.filing_frequency, form_code=profile.form_definition.form_code)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            token = signing.loads(form.cleaned_data['request_token'], salt='client-preparation', max_age=3600)
            if token['actor'] != request.user.pk or token['profile'] != str(profile.pk):
                raise ValidationError('This request belongs to another client or filing. Reload this page.')
            data = {name: form.cleaned_data[name] for name in ('filing_year', 'filing_month' if monthly else 'filing_quarter', 'zero_filing_approved')}
            data.update(zero_filing=True, form_data={} if profile.form_definition.form_code != '2551Q' else {'atc_code': profile.default_atc_code or profile.default_form_data.get('atc_code') or 'PT 010'})
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
