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
    return (client.client_code, client.registered_name, client.combined_tin) in {
        ('DUMMY-CLIENT-001', 'ABC TEST COMPANY', '65070331200000'),
        ('DUMMY-CLIENT-001', 'TEST AUTOMATION COMPANY - TEST ONLY', '63984560200000'),
        ('TEST-639848605-00000', 'Test Company', '63984860500000'),
    }


def scoped_orders(client, form_code='2551Q'):
    if form_code == '1601C':
        return WorkOrder.objects.filter(client=client, form_code='1601C',
            expected_form_number='1601Cv2018', filing_year='2026', filing_month__range=(1, 12)).order_by('id')
    return WorkOrder.objects.filter(client=client, form_code='2551Q',
        expected_form_number='2551Qv2018', filing_year='2026', filing_quarter__in=[1, 2, 3, 4]).order_by('id')


def versions(orders):
    return [[str(order.pk), order.version] for order in orders]


def cleanup_script(orders, *, client=None, form_code='2551Q'):
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
    saved_names = sorted({order.expected_saved_return_name + '.xml' for order in orders})
    if form_code == '1601C':
        if client is None or not is_reset_demo(client):
            raise ValidationError('Monthly cleanup requires the verified test client.')
        saved_names = sorted(set(saved_names) | {
            f'{client.combined_tin}-1601Cv2018-{month:02d}2026.xml' for month in range(1, 13)})
    if any(not re.fullmatch(r'(?:65070331200000|63984560200000|63984860500000)-(?:2551Qv2018-122026Q[1-4]|1601Cv2018-(?:0[1-9]|1[0-2])2026)\.xml', name) for name in saved_names):
        raise ValidationError('Unexpected saved return name. Request operator review.')
    start = source.index('foreach ($quarter in 1..4) {')
    end = source.index('foreach ($orderId in $orderIds)', start)
    source = source[:start] + "$savedReturnFiles = @(" + ','.join("'" + name + "'" for name in saved_names) + ")\n" + (
        "foreach ($name in $savedReturnFiles) {\n"
        "    Preserve-Item (Join-Path 'C:\\eBIRForms\\savefile' $name) 'C:\\eBIRForms\\savefile' $name\n}\n"
    ) + source[end:]
    # Generated scripts must never collect another test client's legacy PDFs.
    start = source.index('# Earlier manual fake-data runs')
    end = source.index('# Preserve the journal last.', start)
    source = source[:start] + source[end:]
    # Preparation outputs are stored under the public WO name, not its UUID.
    source = source.replace('foreach ($orderId in $orderIds) {',
        '$workingNames = @(' + ','.join("'" + name + "'" for name in names) + ')\nforeach ($orderId in $workingNames) {')
    # Never disturb another form's journal or an unresolved Stage 2 attempt.
    source = source.replace("$journalPath = Join-Path $workerDir 'journal.json'", """$stage2Path = Join-Path $workerDir 'stage2-journal.json'
if (Test-Path -LiteralPath $stage2Path) {
    $stage2 = Get-Content -LiteralPath $stage2Path -Raw | ConvertFrom-Json
    $idleStage2Poll = $stage2.Phase -eq 'Requesting' -and $null -eq $stage2.Claim -and $null -eq $stage2.Result
    if ($stage2.Phase -ne 'Completed' -and -not $idleStage2Poll) { throw 'Resolve the Stage 2 journal before cleanup. Nothing was changed.' }
}
$preservePreparationJournal = $true
$journalPath = Join-Path $workerDir 'journal.json'""")
    source = source.replace("throw 'The journal belongs to another work order. Nothing was changed.'", """if ($journal.Phase -ne 'Completed') { throw 'Another work order has an unresolved journal. Nothing was changed.' }
        $preservePreparationJournal = $false""")
    source = source.replace("foreach ($name in @('result.json','journal.pending.json','journal.json')) {", "foreach ($name in @('result.json','journal.pending.json','journal.json')) {\n    if (-not $preservePreparationJournal) { continue }")
    source = source.replace('Create fresh 2026 Q1-Q4 tasks from the dashboard.',
                            'Create fresh tasks only for the selected test form and unsubmitted periods.')
    source = source.replace('# Archives ABC TEST COMPANY, TIN 65070331200000, 2551Qv2018, 2026 Q1-Q4.',
                            '# Archives only the exact test work orders and XML names listed below.')
    marker = 'reset-'  + uuid4().hex + '.done'
    source = source.replace("$journalPath = Join-Path $workerDir 'journal.json'",
        "$doneFile = Join-Path $workerDir '" + marker + "'\n"
        "if (Test-Path -LiteralPath $doneFile) { throw 'This reset script already completed. Do not run it again.' }\n"
        "$journalPath = Join-Path $workerDir 'journal.json'")
    source += "\n[IO.File]::WriteAllText($doneFile, 'Completed')\n"
    return source


class ResetForm(forms.Form):
    form_code = forms.ChoiceField(choices=[('2551Q', '2551Q'), ('1601C', '1601C')], widget=forms.HiddenInput, required=False)
    confirmed_stopped = forms.BooleanField(label='Both Power Automate flows are stopped and eBIRForms is closed.')
    confirmed_scope = forms.BooleanField(label='Reset this test client?s 2551Q test filings for 2026 Q1–Q4. Preserve history and archive files.')
    token = forms.CharField(widget=forms.HiddenInput)


@dashboard_permission('workorders.change_workorder', 'automation_api.change_agent')
@require_http_methods(['GET', 'POST'])
def reset_demo(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    client = get_object_or_404(Client, pk=pk)
    if not is_reset_demo(client):
        raise Http404
    form_code = (request.POST.get('form_code') if request.method == 'POST' else request.GET.get('form')) or '2551Q'
    if form_code not in {'2551Q', '1601C'}:
        raise Http404
    orders = list(scoped_orders(client, form_code))
    initial = {'token': signing.dumps({'actor': request.user.pk, 'client': str(client.pk),
        'form_code': form_code, 'versions': versions(orders)}, salt='demo-reset'), 'form_code': form_code}
    form = ResetForm(request.POST if request.method == 'POST' else None, initial=initial)
    period_label = 'January–December' if form_code == '1601C' else 'Q1–Q4'
    form.fields['confirmed_scope'].label = f'Reset this test client’s {form_code} test filings for 2026 {period_label}. Preserve history and archive files.'
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            data = signing.loads(form.cleaned_data['token'], salt='demo-reset', max_age=900)
            if (data.get('actor') != request.user.pk or data.get('client') != str(client.pk)
                    or data.get('form_code') != form_code):
                raise ValidationError('This confirmation belongs to a different session or client.')
            with transaction.atomic():
                client = Client.objects.select_for_update().get(pk=client.pk)
                if not is_reset_demo(client):
                    raise ValidationError('The fake client details changed. Reset cancelled.')
                orders = list(scoped_orders(client, form_code).select_for_update())
                if versions(orders) != data.get('versions'):
                    raise ValidationError('Tasks changed since you opened this page. Reload and review before resetting.')
                if PreparationAttempt.objects.filter(state='RUNNING',
                                                      stage2_approval__isnull=False).exists():
                    raise ValidationError('Stage 2 has an unresolved attempt. Review its error and recover reporting before resetting. No tasks were reset.')
                script = cleanup_script(orders, client=client, form_code=form_code)
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
        'form': form, 'form_code': form_code, 'period_label': period_label,
        'active_count': sum(not order.is_archived for order in orders), 'section': 'clients'}, status=status)
