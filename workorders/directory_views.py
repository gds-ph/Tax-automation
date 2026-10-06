from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET

from . import client_directory as directory
from .views import dashboard_permission
from .models import RegistrationSetup, RegistrationCardScan
from .registration_cards import saved_cards, registration_source_url
from .cor_selection import select_documents
from .contact_defaults import COMPANY_CONTACT, DEFAULT_RDO_EMAIL


# Mirrors the configured-client page. Everything here is an unreviewed extraction,
# so the details tab describes the certificate, never a saved taxpayer record.
DIRECTORY_TABS = {'details': 'Company details', 'filings': 'Filing cards', 'history': 'History'}
DEFAULT_DIRECTORY_TAB = 'filings'


@dashboard_permission('workorders.view_client')
@require_GET
def detail(request):
    from .client_views import tab_url
    name = request.GET.get('name', '')
    tab = request.GET.get('tab', '')
    tab = tab if tab in DIRECTORY_TABS else DEFAULT_DIRECTORY_TAB
    context = {'default_rdo_email': DEFAULT_RDO_EMAIL, 'company_contact': COMPANY_CONTACT, 'name': name, 'section': 'clients', 'tab': tab, 'tab_label': DIRECTORY_TABS[tab],
               'tabs': [(value, label, tab_url(request, value)) for value, label in DIRECTORY_TABS.items()]}
    context['setup'] = RegistrationSetup.objects.filter(folder=name).select_related('client').first()
    if context['setup'] and request.GET.get('documents') != '1':
        return redirect('workorders:client-detail', pk=context['setup'].client_id)
    if not context['setup']:
        scan = RegistrationCardScan.objects.filter(folder=name).first()
        if scan is None and name not in directory.names():
            raise Http404('Client folder not found.')
        context['scan'] = scan
        if scan and request.user.has_perms(('workorders.add_client', 'workorders.add_clientfilingprofile',
                                           'workorders.view_clientfilingprofile', 'workorders.view_formdefinition')):
            context['card_groups'] = saved_cards(scan, request.user)
            selected, note = select_documents(scan)
            selected_hashes = {d['sha256'] for d in selected}
            context['other_certificates'] = [
                {'name': d['path'].split('/')[-1],
                 'url': registration_source_url(request.user, scan.folder, d['path'])}
                for d in scan.documents if d['sha256'] not in selected_hashes]
            context['selection_note'] = note
            context['card_count'] = sum(len(group['cards']) for group in context['card_groups'])

    else:
        try:
            context.update(directory.registration(name))
            for item in context['files']:
                token = signing.dumps({'actor': request.user.pk, 'client': name, 'path': item['path']}, salt='registration-file')
                item['url'] = reverse('workorders:registration-file') + '?token=' + token
        except directory.DirectoryUnavailable as exc:
            context['error'] = str(exc)
    return render(request, 'workorders/directory_detail.html', context)



@dashboard_permission('workorders.view_client')
@require_GET
def document(request):
    try:
        token = signing.loads(request.GET.get('token', ''), salt='registration-file', max_age=3600)
        if token['actor'] != request.user.pk:
            raise Http404()
    except (signing.BadSignature, KeyError, TypeError):
        raise Http404('Document link expired. Open the client again.')
    try:
        files = directory.registration(token['client'])['files']
        item = next((f for f in files if f['path'] == token['path']), None)
        if item is None:
            raise Http404('Registration document no longer available.')
        data = directory.fetch('/api/file', {'path': item['path']}, limit=50_000_000)
    except directory.DirectoryUnavailable as exc:
        return HttpResponse(str(exc), status=503, content_type='text/plain')
    # Only PDFs are rendered in the browser; other formats are downloads.
    pdf = item['name'].lower().endswith('.pdf') and data.startswith(b'%PDF-')
    response = HttpResponse(data, content_type='application/pdf' if pdf else 'application/octet-stream')
    response['Content-Disposition'] = content_disposition_header(not pdf, item['name'])
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = 'sandbox'
    return response
