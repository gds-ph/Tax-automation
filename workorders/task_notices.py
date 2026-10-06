import hashlib

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from .models import WorkOrder, TaskNoticeRead
from .views import dashboard_permission


def notice(order):
    approval = getattr(order, 'stage2_approval', None)
    receipt = getattr(approval, 'receipt_check', None) if approval else None
    if receipt and receipt.finalized_at and receipt.final_package:
        label = 'Complete — receipt package generated'
    elif order.operational_tone == 'danger':
        label = 'Needs attention — ' + order.operational_status
    elif order.status == 'AWAITING_SUBMISSION_APPROVAL' and not approval:
        label = 'Ready for approval'
    else:
        return None
    state = f'{order.version}:{label}:{approval.state if approval else ""}:{receipt.finalized_at if receipt else ""}'
    kind = 'attention' if label.startswith('Needs attention') else 'complete' if label.startswith('Complete') else 'ready'
    return {'order': order, 'label': label, 'kind': kind, 'token': hashlib.sha256(state.encode()).hexdigest()}


# Things that need a person come first; finished filings are informational.
URGENCY = {'attention': 0, 'ready': 1, 'complete': 2}
VISIBLE_NOTICES = 5


def unread(user):
    reads = dict(TaskNoticeRead.objects.filter(user=user).values_list('work_order_id', 'token'))
    orders = WorkOrder.objects.filter(created_by=user, is_archived=False).select_related('stage2_approval__receipt_check')
    result = []
    for order in orders:
        item = notice(order)
        if item and reads.get(order.pk) != item['token']:
            result.append(item)
    result.sort(key=lambda item: (URGENCY[item['kind']], -item['order'].updated_at.timestamp()))
    return result


def notice_context(items):
    return {'notices': items, 'first_notices': items[:VISIBLE_NOTICES],
            'more_notices': items[VISIBLE_NOTICES:]}


@dashboard_permission('workorders.view_workorder')
@require_GET
def feed(request):
    items = unread(request.user)
    data = {'count': len(items), 'html': render_to_string(
        'workorders/task_notices.html', notice_context(items), request=request)}
    if request.GET.get('workers') == '1':
        from .worker_status import workers
        data['workers_html'] = render_to_string('workorders/worker_status.html', {'workers': workers()}, request=request)
    return JsonResponse(data)


@dashboard_permission('workorders.view_workorder')
@require_POST
def open_notice(request, pk):
    order = get_object_or_404(WorkOrder, pk=pk, created_by=request.user, is_archived=False)
    item = notice(order)
    # A delayed click must not dismiss a newer state the user has not seen.
    if item and request.POST.get('token') == item['token']:
        TaskNoticeRead.objects.update_or_create(user=request.user, work_order=order,
                                               defaults={'token': item['token']})
    return redirect('workorders:detail', pk=pk)


@dashboard_permission('workorders.view_workorder')
@require_POST
def read_all(request):
    """Dismiss exactly the notices that were on screen. The form carries each
    one's token, so a filing whose state changed since the page loaded stays
    unread instead of being cleared unseen."""
    shown = set(request.POST.getlist('token'))
    for item in unread(request.user):
        if item['token'] in shown:
            TaskNoticeRead.objects.update_or_create(user=request.user, work_order=item['order'],
                                                   defaults={'token': item['token']})
    return redirect('workorders:my-tasks')
