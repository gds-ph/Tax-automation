"""Temporary, administrator-only reset for the explicitly configured fake client."""
import re
from pathlib import Path
from uuid import uuid4

from django import forms
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, OperationalError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from automation_api.models import PreparationAttempt
from automation_api.worker_services import abandon
from .archive_services import archive_stopped_order
from .models import Client, WorkOrder
from .views import dashboard_permission


def is_reset_demo(client):
    return (client.client_code == 'DUMMY-CLIENT-001'
        and client.registered_name == 'ABC TEST COMPANY'
        and client.tin1 + client.tin2 + client.tin3 + client.tin4 == '65070331200000')


def scoped_orders(client):
    return WorkOrder.objects.filter(client=client, form_code='2551Q',
        expected_form_number='2551Qv2018', filing_year='2026', filing_quarter__in=[1, 2, 3, 4]).order_by('id')


def versions(orders):
    return [[str(order.pk), order.version] for order in orders]


def cleanup_script(orders):
    # Use only validated server-generated identifiers, never free-form client input.
    ids = [str(order.pk) for order in orders]
    names = [order.work_order_id for order in orders]
    if any(not re.fullmatch(r'WO-[0-9]{4}-[0-9a-f]{32}', name) for name in names):
        raise ValidationError('Unexpected work order identifier. Request operator review.')
    source = (Path(settings.BASE_DIR) / 'worker' / 'Reset-Demo2026.ps1').read_text(encoding='utf-8')
    source = re.sub(r'^\$orderIds.*\n', '', source, flags=re.MULTILINE)
    source = "$orderIds = @(" + ','.join("'" + value + "'" for value in ids) + ")\n" + source
    source = re.sub(r'^    \$allowedNames = .*$',
        '    $allowedNames = @(' + ','.join("'" + value + "'" for value in names) + ')', source, flags=re.MULTILINE)
    marker = 'reset-' + uuid4().hex + '.done'
    source = source.replace("$journalPath = Join-Path $workerDir 'journal.json'",
        "$doneFile = Join-Path $workerDir '" + marker + "'\n"
        "if (Test-Path -LiteralPath $doneFile) { throw 'This reset script already completed. Do not run it again.' }\n"
        "$journalPath = Join-Path $workerDir 'journal.json'")
    source += "\n[IO.File]::WriteAllText($doneFile, 'Completed')\n"
    return source


class ResetForm(forms.Form):
    confirmed_stopped = forms.BooleanField(label='Both Power Automate flows are stopped and eBIRForms is closed.')
    confirmed_scope = forms.BooleanField(label='Reset ABC TEST COMPANY 2551Q test filings for 2026 Q1–Q4. Preserve history and archive files.')
    token = forms.CharField(widget=forms.HiddenInput)


@dashboard_permission('workorders.change_workorder', 'automation_api.change_agent')
@require_http_methods(['GET', 'POST'])
def reset_demo(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    client = get_object_or_404(Client, pk=pk)
    if not is_reset_demo(client):
        raise Http404
    orders = list(scoped_orders(client))
    initial = {'token': signing.dumps({'actor': request.user.pk, 'client': str(client.pk),
        'versions': versions(orders)}, salt='demo-reset')}
    form = ResetForm(request.POST if request.method == 'POST' else None, initial=initial)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            data = signing.loads(form.cleaned_data['token'], salt='demo-reset', max_age=900)
            if data.get('actor') != request.user.pk or data.get('client') != str(client.pk):
                raise ValidationError('This confirmation belongs to a different session or client.')
            with transaction.atomic():
                client = Client.objects.select_for_update().get(pk=client.pk)
                if not is_reset_demo(client):
                    raise ValidationError('The fake client details changed. Reset cancelled.')
                orders = list(scoped_orders(client).select_for_update())
                if versions(orders) != data.get('versions'):
                    raise ValidationError('Tasks changed since you opened this page. Reload and review before resetting.')
                script = cleanup_script(orders)
                for order in orders:
                    if order.is_archived:
                        continue
                    for attempt in PreparationAttempt.objects.filter(work_order=order, state='RUNNING'):
                        abandon(actor=request.user, attempt_id=attempt.pk,
                            expected_version=order.version, confirmed_stopped=True)
                        order.refresh_from_db()
                    archive_stopped_order(actor=request.user, work_order_id=order.pk,
                        expected_version=order.version, confirmed_stopped=True)
            response = HttpResponse(script, content_type='text/plain; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="Reset-Demo2026.ps1"'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        except signing.BadSignature:
            form.add_error(None, 'Confirmation expired or invalid. Reload this page.')
            status = 400
        except ValidationError as error:
            form.add_error(None, error)
            status = 409
        except OperationalError:
            form.add_error(None, 'A task is changing. Keep the worker stopped, then reload this page.')
            status = 409
    return render(request, 'workorders/demo_reset.html', {'taxpayer': client,
        'form': form, 'active_count': sum(not order.is_archived for order in orders), 'section': 'clients'}, status=status)
