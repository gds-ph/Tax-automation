from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET

from . import client_directory as directory
from .views import dashboard_permission
from .models import RegistrationSetup


@dashboard_permission('workorders.view_client')
@require_GET
def detail(request):
    name = request.GET.get('name', '')
    context = {'name': name, 'section': 'clients'}
    context['setup'] = RegistrationSetup.objects.filter(folder=name).select_related('client').first()
    status = 200
    try:
        context.update(directory.registration(name))
        for item in context['files']:
            token = signing.dumps({'actor': request.user.pk, 'client': name, 'path': item['path']}, salt='registration-file')
            item['url'] = reverse('workorders:registration-file') + '?token=' + token
            item['token'] = token
            item['can_read'] = item['name'].lower().endswith('.pdf')
    except directory.DirectoryUnavailable as exc:
        context['error'] = str(exc)
        status = 503
    return render(request, 'workorders/directory_detail.html', context, status=status)


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
