from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import OperationalError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .filing_types import FILING_2551Q, FILING_TYPES
from .forms import TransitionForm, WorkOrderFilterForm, WorkOrderForm
from .models import WorkOrder
from .reference_data.atc_2551qv2018 import ALLOWED_ATCS
from . import services


def dashboard_permission(*permissions):
    """Require login before querying records, and prevent browser/proxy caching."""
    def decorate(view):
        @never_cache
        @login_required
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if not request.user.is_active or not request.user.has_perms(permissions):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return guarded
    return decorate


def _orders():
    return WorkOrder.objects.filter(Q(form_code='2551Q', expected_form_number='2551Qv2018') |
                                    Q(form_code='1601C', expected_form_number='1601Cv2018') |
                                    Q(form_code='1601EQ', expected_form_number='1601EQ') |
                                    Q(form_code='0619F', expected_form_number='0619F') |
                                    Q(form_code='1600VT', expected_form_number='1600VTv2018'))


@dashboard_permission('workorders.view_workorder')
@require_http_methods(['GET', 'POST'])
def gmail_status(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    from automation_api.models import GmailMailbox
    from automation_api.gmail_receipts import test_imap_connection
    mailbox = GmailMailbox.current()
    if request.method == 'POST':
        if not request.user.has_perm('automation_api.change_gmailmailbox'):
            raise PermissionDenied
        address = request.POST.get('address', '').strip()
        password = request.POST.get('app_password', '').strip().replace(' ', '')
        if not address or not password:
            return render(request, 'workorders/gmail_status.html', {'connected': False, 'address': address, 'error': 'Enter both the Gmail address and App Password.', 'section': 'gmail', 'editing': True})
        mailbox = mailbox or GmailMailbox()
        mailbox.address = address
        mailbox.set_app_password(password)
        mailbox.save()
        return redirect('workorders:gmail-status')
    connected = False
    address = mailbox.address if mailbox else settings.GMAIL_ADDRESS
    error = 'Enter the Gmail address and App Password below.'
    if address and (mailbox.app_password() if mailbox else settings.GMAIL_APP_PASSWORD):
        try:
            test_imap_connection()
            connected, error = True, ''
        except Exception:
            error = 'IMAP login failed. Verify the mailbox address and 16-character App Password.'
    return render(request, 'workorders/gmail_status.html', {'connected': connected, 'address': address, 'error': error, 'section': 'gmail', 'editing': not connected})


def _filing(slug):
    from django.http import Http404
    for filing in FILING_TYPES:
        if filing.slug == slug:
            return filing
    raise Http404("Unsupported filing type")


@dashboard_permission("workorders.view_workorder")
@require_GET
def filing_types(request):
    counts = _orders().aggregate(total=Count("pk"), drafts=Count("pk", filter=Q(status="DRAFT")), ready=Count("pk", filter=Q(status="READY_TO_PREPARE")))
    return render(request, "workorders/filing_types.html", {"filing_types": FILING_TYPES, "counts": counts, "section": "filings"})


@dashboard_permission("workorders.view_workorder")
@require_GET
def work_order_list(request, filing_slug="2551q", mine=False):
    from .task_notices import unread, notice_context
    from .worker_status import workers
    filing = _filing(filing_slug)
    orders = _orders().filter(is_archived=False).select_related('assigned_to', 'created_by')
    if mine:
        orders = orders.filter(created_by=request.user)
    form = WorkOrderFilterForm(request.GET)
    if form.is_valid():
        values = form.cleaned_data
        if values["client"]:
            orders = orders.filter(Q(client_name__icontains=values["client"]) | Q(legacy_client_reference__icontains=values["client"]))
        for field, query_key in (("status", "status"), ("filing_year", "year"), ("filing_quarter", "quarter"), ('filing_month', 'month')):
            if values[query_key]:
                orders = orders.filter(**{field: values[query_key]})
    else:
        orders = orders.none()
    from .dashboard_actions import operational_orders, kpi_filters
    metrics = []
    operational = operational_orders(orders)
    selected_kpi = request.GET.get('kpi', '')
    for key, label, query in kpi_filters():
        link = request.GET.copy()
        link.pop('page', None)
        link['kpi'] = key
        metrics.append({'key': key, 'label': label, 'count': operational.filter(query).count(), 'url': '?' + link.urlencode()})
        if selected_kpi == key:
            selected_orders = operational.filter(query)
    if selected_kpi in {item['key'] for item in metrics}:
        orders = selected_orders
    page = Paginator(orders.select_related('stage2_approval__receipt_check'), 20).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "workorders/list.html", {
        "filing": filing, "filter_form": form, "page_obj": page, "metrics": metrics, "selected_kpi": selected_kpi,
        "filter_query": params.urlencode(), "section": "tasks" if mine else "orders",
        "mine": mine, **notice_context(unread(request.user) if mine else []), "workers": workers(),
        "has_filters": any(request.GET.get(key) for key in ("client", "status", "year", "quarter", 'month', 'kpi')),
    })


def _add_errors(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, error)


def _edit_screen(request, order=None):
    form = WorkOrderForm(request.POST if request.method == "POST" else None, instance=order)
    response_status = 200
    if request.method == "POST" and form.is_valid():
        try:
            if order is None:
                saved = services.create_work_order(actor=request.user, data=form.source_data(), client_filing_profile_id=form.cleaned_data["client_filing_profile"].pk)
            else:
                saved = services.edit_work_order(work_order_id=order.pk, actor=request.user,
                                                expected_version=form.cleaned_data["expected_version"], changes=form.source_data())
        except ValidationError as error:
            _add_errors(form, error)
            response_status = 409
        except OperationalError as error:
            if "locked" not in str(error).lower():
                raise
            form.add_error(None, "Another update is in progress. Wait briefly, reload the record, and try again.")
            response_status = 409
        else:
            messages.success(request, "Work order saved." if order else "Work order created as a draft.")
            return redirect("workorders:detail", pk=saved.pk)
    return render(request, "workorders/form.html", {
        "form": form, "order": order, "filing": FILING_2551Q,
        "atcs": sorted(ALLOWED_ATCS), "section": "orders",
    }, status=response_status)


@dashboard_permission("workorders.view_workorder", "workorders.add_workorder")
@require_http_methods(["GET", "POST"])
def work_order_create(request, filing_slug="2551q"):
    _filing(filing_slug)
    return redirect("workorders:clients")


@dashboard_permission("workorders.view_workorder", "workorders.change_workorder")
@require_http_methods(["GET", "POST"])
def work_order_edit(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    if order.status not in {"DRAFT", "READY_TO_PREPARE"}:
        raise PermissionDenied("Claimed and completed filings cannot be edited.")
    return _edit_screen(request, order)


ORDER_TABS = {'overview': 'Overview', 'documents': 'Documents', 'activity': 'Activity'}
STAGE2_FAILURES = {'SUBMISSION_UNCONFIRMED', 'FAILED_SYSTEM', 'ABANDONED', 'BLOCKED_NOT_APPROVED',
                   'WORK_ORDER_VERIFICATION_FAILED', 'SAVED_RETURN_NOT_UNIQUE', 'SAVED_RETURN_ROW_NOT_FOUND'}
SUBMITTED_STATES = {'SUBMITTED_WAITING_FOR_CONFIRMATION', 'BIR_RECEIPT_CONFIRMED', 'MANUALLY_SUBMITTED_UNVERIFIED'}


OVERVIEW_RANGES = {'today': 0, '7d': 6, '30d': 29}
OVERVIEW_FORMS = {'2551Q': '2551Q', '1601C': '1601C', '1601EQ': '1601EQ'}


def _overview_range(request):
    """Resolve the reporting window in Manila dates, falling back to 30 days."""
    from datetime import date, timedelta
    from django.utils import timezone
    today = timezone.localdate()
    preset = request.GET.get('range', '')
    if preset == 'month':
        return today.replace(day=1), today, 'month'
    if preset in OVERVIEW_RANGES:
        return today - timedelta(days=OVERVIEW_RANGES[preset]), today, preset
    def parsed(name):
        try:
            return date.fromisoformat(request.GET.get(name, ''))
        except ValueError:
            return None
    start, end = parsed('start'), parsed('end')
    if start and end and start <= end:
        return start, end, ''
    return today - timedelta(days=29), today, '30d'


def _overview_rows(request):
    start, end, preset = _overview_range(request)
    form_code = OVERVIEW_FORMS.get(request.GET.get('form', ''), '')
    orders = _orders().filter(is_archived=False, created_at__date__gte=start, created_at__date__lte=end)
    if form_code:
        orders = orders.filter(form_code=form_code)
    orders = orders.select_related('stage2_approval__receipt_check').order_by('-created_at', 'id')
    return list(orders), start, end, preset, form_code


def _overview_csv(rows, start, end):
    """Authorized export. Values that spreadsheets would read as formulas are
    quoted so an opened file cannot execute a cell."""
    import csv
    import io
    from django.http import HttpResponse
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['Work order', 'Client', 'TIN', 'Form', 'Period', 'Status', 'Created', 'Receipt received'])
    for order in rows:
        approval = getattr(order, 'stage2_approval', None)
        receipt = getattr(approval, 'receipt_check', None) if approval else None
        writer.writerow([_csv_safe(value) for value in (
            order.work_order_id, order.client_name,
            f'{order.tin1}-{order.tin2}-{order.tin3}-{order.tin4}',
            order.form_code, order.period_label, order.operational_status,
            order.created_at.strftime('%Y-%m-%d %H:%M'),
            receipt.received_at.strftime('%Y-%m-%d %H:%M') if receipt and receipt.received_at else '',
        )])
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="filings-{start:%Y%m%d}-{end:%Y%m%d}.csv"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _csv_safe(value):
    text = str(value)
    return "'" + text if text[:1] in {'=', '+', '-', '@', '\t', '\r'} else text


@dashboard_permission('workorders.view_workorder')
@require_GET
def overview(request):
    from automation_api.models import Agent
    from django.utils import timezone
    from datetime import timedelta
    rows, start, end, preset, form_code = _overview_rows(request)
    if request.GET.get('export') == 'csv':
        return _overview_csv(rows, start, end)
    forms, statuses = {}, {}
    submitted = awaiting = receipted = 0
    for order in rows:
        approval = getattr(order, 'stage2_approval', None)
        receipt = getattr(approval, 'receipt_check', None) if approval else None
        forms[order.form_code] = forms.get(order.form_code, 0) + 1
        label = order.operational_status
        statuses[label] = statuses.get(label, 0) + 1
        if approval and approval.state in SUBMITTED_STATES:
            submitted += 1
        if order.status == 'AWAITING_SUBMISSION_APPROVAL' and not approval:
            awaiting += 1
        if receipt and receipt.received_at:
            receipted += 1
    worker = Agent.objects.order_by('name').first()
    worker_online = bool(worker and worker.is_active and worker.last_seen_at and
                         worker.last_seen_at >= timezone.now() - timedelta(minutes=2))
    # timesince() reports "0 minutes" for a fresh heartbeat, which reads oddly
    # on a panel whose whole point is that the worker just checked in.
    heartbeat = ''
    if worker and worker.last_seen_at:
        from django.utils.timesince import timesince
        elapsed = timezone.now() - worker.last_seen_at
        heartbeat = 'just now' if elapsed.total_seconds() < 60 else f'{timesince(worker.last_seen_at)} ago'
    return render(request, 'workorders/overview.html', {
        'section': 'overview', 'rows': rows[:25], 'row_count': len(rows),
        'start': start, 'end': end, 'preset': preset, 'form_code': form_code,
        'totals': {'filings': len(rows), 'submitted': submitted,
                   'awaiting': awaiting, 'receipted': receipted},
        'by_form': sorted(forms.items(), key=lambda item: -item[1]),
        'by_status': sorted(statuses.items(), key=lambda item: -item[1]),
        'worker': worker, 'worker_online': worker_online, 'worker_heartbeat': heartbeat,
    })


def _stages(order, approval, receipt):
    """One rail for the whole life of a filing; the first incomplete step is the
    current one, and it shows as failed when that step reported a failure."""
    from automation_api.worker_policy import FAILURE_STATUSES
    reached = (
        ('Prepared', order.status == 'AWAITING_SUBMISSION_APPROVAL'),
        ('Approved', bool(approval)),
        ('Submitted', bool(approval and approval.state in SUBMITTED_STATES)),
        ('BIR receipt', bool(receipt and receipt.received_at)),
        ('Final package', bool(receipt and receipt.finalized_at)),
    )
    failing = order.status in FAILURE_STATUSES or bool(approval and approval.state in STAGE2_FAILURES)
    stages, seen_current = [], False
    for label, done in reached:
        if done:
            stages.append({'label': label, 'state': 'complete'})
        elif not seen_current:
            seen_current = True
            stages.append({'label': label, 'state': 'failed' if failing else 'current'})
        else:
            stages.append({'label': label, 'state': 'pending'})
    return stages


def _detail_screen(request, order, *, error=None, status=200):
    events = order.audit_events.select_related("actor", "performed_by_agent").order_by("-created_at", "-id")
    # Access to the work order alone does not grant access to its audit history.
    can_view_audit = request.user.has_perm("audit.view_auditevent")
    approval = getattr(order, 'stage2_approval', None)
    receipt = getattr(approval, 'receipt_check', None) if approval else None
    from .receipt_activity import receipt_activity
    history = list(events) + receipt_activity(receipt) if can_view_audit else []
    history.sort(key=lambda event: event.created_at, reverse=True)
    page = Paginator(history, 20).get_page(request.GET.get("history_page"))
    status_labels = dict(WorkOrder.Status.choices)
    for event in page:
        event.old_status_label = status_labels.get(event.old_status, event.old_status)
        event.new_status_label = status_labels.get(event.new_status, event.new_status)
        event.changed_labels = [str(WorkOrder._meta.get_field(name).verbose_name).replace("_", " ").capitalize()
                                for name in event.changed_fields if name in {field.name for field in WorkOrder._meta.fields}]
    approval = getattr(order, 'stage2_approval', None)
    receipt = getattr(approval, 'receipt_check', None) if approval else None
    running_attempt = order.preparation_attempts.filter(state='RUNNING').first()
    can_view_pdf = request.user.has_perm('workorders.view_prepared_pdf')
    documents = sum((
        bool(order.prepared_pdf) and can_view_pdf,
        bool(approval and approval.success_screenshot) and can_view_pdf,
        bool(receipt and receipt.received_at),
        bool(receipt and receipt.finalized_at) and can_view_pdf,
    ))
    tab = request.GET.get('tab', '')
    tab = tab if tab in ORDER_TABS else 'overview'
    from .dashboard_actions import archive_blocker, cancellation_blocker, can_cancel_filing
    can_cancel = can_cancel_filing(request.user) and not cancellation_blocker(order)
    can_archive = request.user.has_perms(["workorders.change_workorder", "automation_api.change_agent"]) and not archive_blocker(order)
    base = request.path
    return render(request, "workorders/detail.html", {
        "order": order, "can_archive": can_archive, "can_cancel": can_cancel, "filing": FILING_2551Q, "history": page, "can_view_audit": can_view_audit,
        "transition_form": TransitionForm(initial={"expected_version": order.version}),
        "action_error": error, "section": "orders",
        "approval": approval, "receipt": receipt, "can_view_pdf": can_view_pdf,
        "cancellation_cleanup": getattr(order, 'cancellation_cleanup', None),
        "running_attempt": running_attempt,
        "can_retry_preparation": request.user.has_perm('workorders.change_workorder') and not services.preparation_retry_blocker(order),
        "stages": _stages(order, approval, receipt), "tab": tab, "document_count": documents,
        "tabs": [(value, label, f'{base}?tab={value}') for value, label in ORDER_TABS.items()],
        "refresh_url": f'{base}?tab={tab}',
    }, status=status)


@dashboard_permission("workorders.view_workorder")
@require_GET
def work_order_detail(request, pk):
    return _detail_screen(request, get_object_or_404(_orders(), pk=pk))


def _transition(request, pk, target):
    order = get_object_or_404(_orders(), pk=pk)
    form = TransitionForm(request.POST)
    if not form.is_valid():
        return _detail_screen(request, order, error="The form is incomplete. Reload this page and try again.", status=400)
    try:
        services.transition_work_order(work_order_id=order.pk, actor=request.user,
                                       expected_version=form.cleaned_data["expected_version"], target=target)
    except ValidationError as error:
        return _detail_screen(request, order, error=" ".join(error.messages), status=409)
    except OperationalError as error:
        if "locked" not in str(error).lower():
            raise
        return _detail_screen(request, order, error="Another update is in progress. Reload and try again.", status=409)
    messages.success(request, "Work order marked ready to prepare." if target == "READY_TO_PREPARE" else "Work order returned to draft.")
    return redirect("workorders:detail", pk=order.pk)


@dashboard_permission("workorders.view_workorder", "workorders.change_workorder")
@require_POST
def work_order_ready(request, pk):
    return _transition(request, pk, WorkOrder.Status.READY_TO_PREPARE)


@dashboard_permission('workorders.view_workorder', 'workorders.change_workorder')
@require_POST
def work_order_retry(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    form = TransitionForm(request.POST)
    if not form.is_valid():
        return _detail_screen(request, order, error='Reload this page before retrying.', status=400)
    try:
        services.retry_preparation(work_order_id=order.pk, actor=request.user,
                                   expected_version=form.cleaned_data['expected_version'])
    except ValidationError as error:
        return _detail_screen(request, order, error=' '.join(error.messages), status=409)
    except OperationalError as error:
        if 'locked' not in str(error).lower():
            raise
        return _detail_screen(request, order, error='Another update is in progress. Reload and try again.', status=409)
    messages.success(request, 'Preparation queued again. The previous attempt remains in Activity history.')
    return redirect('workorders:detail', pk=order.pk)


@dashboard_permission("workorders.view_workorder", "workorders.change_workorder")
@require_POST
def work_order_draft(request, pk):
    return _transition(request, pk, WorkOrder.Status.DRAFT)


@dashboard_permission('workorders.view_workorder', 'workorders.change_workorder', 'automation_api.change_agent')
@require_POST
def release_interrupted_run(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    if request.POST.get('confirmed_stopped') != 'on':
        return _detail_screen(request, order, error='Confirm that PAD and the desktop filing flow are stopped.', status=400)
    try:
        from automation_api.worker_services import abandon
        attempt = order.preparation_attempts.filter(pk=request.POST.get('attempt_id'), state='RUNNING').first()
        if not attempt or hasattr(attempt, 'stage2_approval'):
            raise ValidationError('This preparation attempt does not belong to the filing.')
        abandon(actor=request.user, attempt_id=attempt.pk,
                expected_version=int(request.POST.get('version', '0')), confirmed_stopped=True)
    except (ValidationError, OperationalError, ValueError):
        return _detail_screen(request, order, error='The interrupted run changed or could not be released. Reload and review it.', status=409)
    messages.success(request, 'Interrupted run released. Restart the updated parent worker to clear its matching pending journal, then use Retry preparation.')
    return redirect('workorders:detail', pk=pk)


@dashboard_permission('workorders.view_workorder', 'automation_api.change_agent')
@require_GET
def worker_recovery_update(request):
    import io
    import zipfile
    from django.http import FileResponse
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for name in ('WorkerBridge.ps1', 'Install-DashboardRecovery.ps1', 'Install-DashboardRecovery.cmd'):
            package.write(settings.BASE_DIR / 'worker' / name, arcname=name)
        package.writestr('README.txt',
            'Stop both parent and child PAD flows. Extract all files on the automation VM.\n'
            'Double-click Install-DashboardRecovery.cmd. No commands need to be pasted.\n'
            'This updates C:\\TaxAutomation\\WorkerBridge.ps1 and backs up the previous script.\n'
            'Configuration and journals are preserved.\n\n'
            'In the dashboard, open the interrupted filing and choose Release interrupted run.\n'
            'Confirm both PAD flows stopped. Start one parent worker; it backs up and clears\n'
            'only the matching released preparation journal. Then choose Retry preparation.\n'
            'Publishing results and submission journals still require separate review.\n')
    archive.seek(0)
    return FileResponse(archive, as_attachment=True, filename='DashboardRecovery-Update.zip')


@dashboard_permission('workorders.view_workorder', 'workorders.change_workorder',
                      'automation_api.change_agent', 'automation_api.approve_stage2')
@require_POST
def retry_submission(request, pk):
    import io
    import uuid
    import zipfile
    from django.http import FileResponse
    from automation_api.stage2 import recover_before_submit
    from automation_api.worker_services import WorkerError
    order = get_object_or_404(_orders(), pk=pk)
    approval = getattr(order, 'stage2_approval', None)
    if request.POST.get('confirmed_stopped_before_submit') != 'on':
        return _detail_screen(request, order, error='Confirm both PAD flows are stopped and Submit was never clicked.', status=400)
    try:
        attempt_id = uuid.UUID(request.POST.get('attempt_id', ''))
        if not approval:
            raise ValidationError('No submission approval exists.')
        # Prepare the download before changing the server state.
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
            package.write(settings.BASE_DIR / 'worker' / 'Recover-Stage2BeforeSubmit.ps1',
                          arcname='Recover-Stage2BeforeSubmit.ps1')
            package.writestr('Recover.cmd', '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Recover-Stage2BeforeSubmit.ps1" -AttemptId ' + str(attempt_id) + '\r\npause\r\n')
            package.writestr('README.txt',
                'Keep both PAD flows stopped. Extract all files on the automation VM.\n'
                'Double-click Recover.cmd under the Windows account that runs PAD.\n'
                'After recovery succeeds, restart one parent worker.\n'
                'The approved return is queued again. The previous attempt and journal are preserved.\n'
                'If recovery fails, do not delete journals or manually resubmit.\n')
        recover_before_submit(actor=request.user, approval_id=approval.pk,
            expected_attempt_id=attempt_id, confirmed_not_submitted=True,
            evidence_note=request.POST.get('evidence_note', ''))
    except (ValidationError, WorkerError, ValueError) as error:
        return _detail_screen(request, order, error=str(error), status=409)
    archive.seek(0)
    return FileResponse(archive, as_attachment=True, filename=f'SubmissionRecovery-{attempt_id}.zip')


@dashboard_permission("workorders.view_workorder", "workorders.view_prepared_pdf")
@require_GET
def prepared_pdf_download(request, pk):
    from django.http import FileResponse, Http404
    from automation_api.worker_services import verify_stored_pdf, WorkerError
    order = get_object_or_404(_orders(), pk=pk, status__in=["AWAITING_SUBMISSION_APPROVAL", "CANCELLED"])
    try:
        path = verify_stored_pdf(order)
        inline = request.GET.get("inline") == "1"
        response = FileResponse(path.open("rb"), as_attachment=not inline, filename=order.review_pdf_filename, content_type="application/pdf")
    except (WorkerError, OSError):
        raise Http404("The protected PDF is unavailable or failed its integrity check.") from None
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["X-Content-Type-Options"] = "nosniff"
    if inline:
        response["X-Frame-Options"] = "SAMEORIGIN"
        response["Content-Security-Policy"] += "; frame-ancestors 'self'"
    return response


@dashboard_permission('workorders.view_workorder', 'workorders.view_prepared_pdf', 'automation_api.approve_stage2')
@require_POST
def approve_stage2(request, pk):
    from automation_api.stage2 import approve
    from automation_api.worker_services import WorkerError
    order=get_object_or_404(_orders(), pk=pk)
    if request.POST.get('authorize_submission') != 'on':
        return _detail_screen(request, order, error='Confirm authorization to submit this exact reviewed return.', status=400)
    try:
        approve(actor=request.user, order_id=pk, version=int(request.POST.get('version', '0')),
                digest=request.POST.get('pdf_sha256', ''), comment=request.POST.get('comment', '')[:2000],
                submission_enabled=request.POST.get('authorize_submission') == 'on')
    except (ValidationError, WorkerError, ValueError, OperationalError):
        return _detail_screen(request, order, error='Stage 2 could not be approved. Reload and check the prepared PDF and current job state.', status=409)
    messages.success(request, 'Submission approved and queued for the Stage 2 worker.')
    return redirect('workorders:detail', pk=pk)


@dashboard_permission('workorders.view_workorder', 'workorders.view_prepared_pdf')
@require_GET
def submission_screenshot(request, pk):
    from django.http import FileResponse, Http404
    from automation_api.models import Stage2Approval
    from automation_api.stage2 import screenshot_path
    from automation_api.worker_services import WorkerError
    approval = get_object_or_404(Stage2Approval, work_order_id=pk)
    try:
        path = screenshot_path(approval)
    except WorkerError:
        raise Http404('Submission evidence is unavailable.') from None
    response = FileResponse(path.open('rb'), content_type='image/png')
    response['Content-Disposition'] = 'inline; filename="submission-success.png"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


@dashboard_permission('workorders.view_workorder', 'workorders.view_prepared_pdf')
@require_GET
def final_package_download(request, pk):
    from django.http import FileResponse, Http404
    from automation_api.models import BirReceiptCheck
    check = get_object_or_404(BirReceiptCheck, approval__work_order_id=pk)
    root = settings.MEDIA_ROOT.resolve()
    path = (root / check.final_package).resolve()
    if not check.final_package or not path.is_relative_to(root) or not path.is_file(): raise Http404('Final package is unavailable.')
    response=FileResponse(path.open('rb'), content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') == '1' else 'attachment'
    response['Content-Disposition']=f'{disposition}; filename="{path.name}"'; response['X-Content-Type-Options']='nosniff'; return response


@dashboard_permission('workorders.view_workorder', 'workorders.change_workorder')
@require_POST
def assign_work_order(request, pk):
    from .assignments import AssignmentForm, assign
    order = get_object_or_404(WorkOrder, pk=pk)
    form = AssignmentForm(request.POST)
    if not form.is_valid():
        return _detail_screen(request, order, error='Choose a valid team member and reload if the assignment changed.', status=400)
    try:
        assign(actor=request.user, pk=pk, **form.cleaned_data)
    except ValidationError as error:
        order.refresh_from_db()
        return _detail_screen(request, order, error=' '.join(error.messages), status=409)
    messages.success(request, 'Assignment saved.')
    return redirect('workorders:detail', pk=pk)


@dashboard_permission('workorders.view_workorder', 'workorders.change_workorder', 'automation_api.change_agent')
@require_POST
def work_order_archive(request, pk):
    from .dashboard_actions import archive_order
    order = get_object_or_404(_orders(), pk=pk)
    form = TransitionForm(request.POST)
    if not form.is_valid() or request.POST.get('confirmed') != 'yes':
        return _detail_screen(request, order, error='Confirm archival and reload if the form is outdated.', status=400)
    try:
        archive_order(actor=request.user, work_order_id=pk, expected_version=form.cleaned_data['expected_version'])
    except (ValidationError, OperationalError) as error:
        order.refresh_from_db()
        message = ' '.join(error.messages) if isinstance(error, ValidationError) else 'Another update is in progress. Reload and try again.'
        return _detail_screen(request, order, error=message, status=409)
    messages.success(request, 'Filing archived. History and documents are preserved.')
    return redirect('workorders:list')


@dashboard_permission('workorders.view_workorder')
@require_POST
def work_order_cancel(request, pk):
    from .dashboard_actions import cancel_order, can_cancel_filing
    if not can_cancel_filing(request.user):
        raise PermissionDenied('Filing edit or submission approval permission is required.')
    order = get_object_or_404(_orders(), pk=pk)
    form = TransitionForm(request.POST)
    if not form.is_valid() or request.POST.get('confirmed') != 'yes':
        return _detail_screen(request, order, error='Confirm cancellation and reload if the form is outdated.', status=400)
    try:
        cancel_order(actor=request.user, work_order_id=pk, expected_version=form.cleaned_data['expected_version'])
    except (ValidationError, OperationalError) as error:
        order.refresh_from_db()
        message = ' '.join(error.messages) if isinstance(error, ValidationError) else 'Another update is in progress. Reload and try again.'
        return _detail_screen(request, order, error=message, status=409)
    messages.success(request, 'Filing cancelled. XML archive cleanup is queued for the original VM. History and PDFs are preserved.')
    return redirect('workorders:detail', pk=pk)


@dashboard_permission('workorders.view_workorder', 'automation_api.change_agent')
@require_GET
def cancellation_worker_update(request):
    if not request.user.is_superuser:
        raise PermissionDenied('Only administrators can download VM updates.')
    import io
    import zipfile
    from django.http import FileResponse
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for name in ('WorkerBridge.ps1', 'Archive-CancelledReturn.ps1',
                     'Install-CancellationCleanup.ps1', 'Install-CancellationCleanup.cmd'):
            package.write(settings.BASE_DIR / 'worker' / name, arcname=name)
        package.write(settings.BASE_DIR / 'docs' / 'cancelled-xml-cleanup.md', arcname='README.md')
        package.writestr('README.txt',
            'Stop parent and child PAD flows. Extract all files on the automation VM.\n'
            'Run Install-CancellationCleanup.cmd. Close eBIRForms form windows.\n'
            'Start one parent worker. Cancelled XML cleanup runs before new desktop work.\n'
            'XML is moved into C:\\TaxAutomation\\Archive\\Cancelled\\<WorkOrderId>.\n'
            'PDF files and dashboard history are retained in their existing locations.\n'
            'Missing, changed or shared XML requires operator review; no files are overwritten.\n')
    archive.seek(0)
    return FileResponse(archive, as_attachment=True, filename='CancellationCleanup-Update.zip')
