from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import OperationalError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
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
    return WorkOrder.objects.filter(form_code=FILING_2551Q.code, expected_form_number=FILING_2551Q.version)


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
def work_order_list(request, filing_slug="2551q"):
    filing = _filing(filing_slug)
    orders = _orders().filter(is_archived=False)
    form = WorkOrderFilterForm(request.GET)
    if form.is_valid():
        values = form.cleaned_data
        if values["client"]:
            orders = orders.filter(Q(client_name__icontains=values["client"]) | Q(legacy_client_reference__icontains=values["client"]))
        for field, query_key in (("status", "status"), ("filing_year", "year"), ("filing_quarter", "quarter")):
            if values[query_key]:
                orders = orders.filter(**{field: values[query_key]})
    else:
        orders = orders.none()
    page = Paginator(orders, 20).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "workorders/list.html", {
        "filing": filing, "filter_form": form, "page_obj": page,
        "filter_query": params.urlencode(), "section": "orders",
        "has_filters": any(request.GET.get(key) for key in ("client", "status", "year", "quarter")),
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
    return _edit_screen(request)


@dashboard_permission("workorders.view_workorder", "workorders.change_workorder")
@require_http_methods(["GET", "POST"])
def work_order_edit(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    if order.status not in {"DRAFT", "READY_TO_PREPARE"}:
        raise PermissionDenied("Claimed and completed filings cannot be edited.")
    return _edit_screen(request, order)


def _detail_screen(request, order, *, error=None, status=200):
    events = order.audit_events.select_related("actor", "performed_by_agent").order_by("-created_at", "-id")
    # Access to the work order alone does not grant access to its audit history.
    can_view_audit = request.user.has_perm("audit.view_auditevent")
    page = Paginator(events if can_view_audit else events.none(), 20).get_page(request.GET.get("history_page"))
    status_labels = dict(WorkOrder.Status.choices)
    for event in page:
        event.old_status_label = status_labels.get(event.old_status, event.old_status)
        event.new_status_label = status_labels.get(event.new_status, event.new_status)
        event.changed_labels = [str(WorkOrder._meta.get_field(name).verbose_name).replace("_", " ").capitalize()
                                for name in event.changed_fields if name in {field.name for field in WorkOrder._meta.fields}]
    return render(request, "workorders/detail.html", {
        "order": order, "filing": FILING_2551Q, "history": page, "can_view_audit": can_view_audit,
        "transition_form": TransitionForm(initial={"expected_version": order.version}),
        "action_error": error, "section": "orders",
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


@dashboard_permission("workorders.view_workorder", "workorders.change_workorder")
@require_POST
def work_order_draft(request, pk):
    return _transition(request, pk, WorkOrder.Status.DRAFT)


@dashboard_permission("workorders.view_workorder", "workorders.view_prepared_pdf")
@require_GET
def prepared_pdf_download(request, pk):
    from django.http import FileResponse, Http404
    from automation_api.worker_services import verify_stored_pdf, WorkerError
    order = get_object_or_404(_orders(), pk=pk, status="AWAITING_SUBMISSION_APPROVAL")
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
    try:
        approve(actor=request.user, order_id=pk, version=int(request.POST.get('version', '0')),
                digest=request.POST.get('pdf_sha256', ''), comment=request.POST.get('comment', '')[:2000])
    except (ValidationError, WorkerError, ValueError, OperationalError):
        return _detail_screen(request, order, error='Stage 2 could not be approved. Reload and check the prepared PDF and current job state.', status=409)
    messages.success(request, 'Stage 2 revalidation queued. Actual BIR submission remains disabled.')
    return redirect('workorders:detail', pk=pk)
