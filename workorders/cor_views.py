import hashlib
import uuid
from django.contrib import messages
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from . import client_directory as directory
from .cor_extraction import read_cor, FORM_CATALOG
from .cor_forms import CORReviewForm
from .cor_services import save_setup
from .models import RegistrationSetup
from .views import dashboard_permission

PERMISSIONS = ('workorders.view_client', 'workorders.add_client', 'workorders.add_clientfilingprofile',
               'workorders.view_clientfilingprofile', 'workorders.view_formdefinition')


def source_document(folder, path):
    files = directory.registration(folder)['files']
    if not any(f['path'] == path and f['name'].lower().endswith('.pdf') for f in files):
        raise Http404('Choose a current registration PDF for this client.')
    return directory.fetch('/api/file', {'path': path}, limit=20_000_000)


@dashboard_permission(*PERMISSIONS)
@require_POST
def read(request):
    try:
        token = signing.loads(request.POST.get('token', ''), salt='registration-file', max_age=3600)
        if token['actor'] != request.user.pk:
            raise Http404()
    except (signing.BadSignature, KeyError, TypeError):
        raise Http404('Document link expired. Open the client again.')
    folder, path = token['client'], token['path']
    existing = RegistrationSetup.objects.filter(folder=folder).first()
    if existing:
        return redirect('workorders:client-detail', pk=existing.client_id)
    try:
        data = source_document(folder, path)
        digest = hashlib.sha256(data).hexdigest()
        scan_key = 'cor-scan:v3:' + digest
        result = cache.get(scan_key)
        if result is None:
            result = read_cor(data)
            cache.set(scan_key, result, 3600)
    except (ValidationError, directory.DirectoryUnavailable) as exc:
        return render(request, 'workorders/cor_error.html', {'folder': folder,
            'errors': exc.messages if isinstance(exc, ValidationError) else [str(exc)], 'section': 'clients'}, status=422)
    draft_id = uuid.uuid4()
    draft = result | {'actor': request.user.pk, 'folder': folder, 'path': path,
                      'sha256': hashlib.sha256(data).hexdigest()}
    cache.set('cor-review:' + str(draft_id), draft, 3600)
    if request.POST.get('cards') == '1':
        cards = []
        seen = set()
        for row in result['rows']:
            code = row['form_code'].strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            title, frequency = FORM_CATALOG.get(code, (row['tax_type'] or 'Registration entry', row['frequency']))
            cards.append({'code': code, 'title': title, 'frequency': frequency,
                          'uncertain': row['uncertain'] or code not in result['initial']['filings']})
        return render(request, 'workorders/cor_cards.html', {'cards': cards, 'draft': draft,
                      'draft_id': draft_id, 'digest': digest})
    return redirect('workorders:cor-review', draft_id=draft_id)


@dashboard_permission(*PERMISSIONS)
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters()
def review(request, draft_id):
    draft = cache.get('cor-review:' + str(draft_id))
    if not draft or draft['actor'] != request.user.pk:
        return render(request, 'workorders/cor_error.html', {'errors': ['This review expired or belongs to another user. Open the client and read the COR again.'], 'section': 'clients'}, status=410)
    existing = RegistrationSetup.objects.filter(folder=draft['folder']).first()
    if existing:
        return redirect('workorders:client-detail', pk=existing.client_id)
    form = CORReviewForm(request.POST if request.method == 'POST' else None, initial=draft['initial'])
    if request.method == 'POST' and form.is_valid():
        try:
            current = source_document(draft['folder'], draft['path'])
            if hashlib.sha256(current).hexdigest() != draft['sha256']:
                raise ValidationError('The source PDF changed after reading. Read the current COR again before saving.')
            client = save_setup(actor=request.user, draft=draft, cleaned=form.cleaned_data)
        except (ValidationError, directory.DirectoryUnavailable) as exc:
            for message in (exc.messages if isinstance(exc, ValidationError) else [str(exc)]):
                form.add_error(None, message)
        except (IntegrityError, OperationalError):
            form.add_error(None, 'Another setup may have been saved at the same time. Reload to check; no partial setup was saved.')
        else:
            messages.success(request, 'Filing setup saved. No filing task has been queued.')
            return redirect('workorders:client-detail', pk=client.pk)
    token = signing.dumps({'actor': request.user.pk, 'client': draft['folder'], 'path': draft['path']}, salt='registration-file')
    return render(request, 'workorders/cor_review.html', {'form': form, 'draft': draft, 'section': 'clients',
        'source_url': reverse('workorders:registration-file') + '?token=' + token})
