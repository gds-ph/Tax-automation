"""Operational counters and guarded archival for the dashboard."""
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from audit.models import AuditEvent
from .catalog_services import require_permission
from .services import _load_current, _persist

TEST_CODES = ('DUMMY-CLIENT-001', 'TEST-639848605-00000', 'TEST-639852610-00000')

def operational_orders(orders):
    return orders.filter(is_archived=False).exclude(client__client_code__in=TEST_CODES)

def kpi_filters():
    from automation_api.worker_policy import FAILURE_STATUSES
    from .views import STAGE2_FAILURES
    today = timezone.localdate()
    return [
        ('approval', 'Awaiting approval', Q(status='AWAITING_SUBMISSION_APPROVAL', stage2_approval__isnull=True)),
        ('progress', 'In progress', Q(status__in=['READY_TO_PREPARE', 'PROCESSING_PREPARATION']) | Q(stage2_approval__state__in=['QUEUED', 'RUNNING'])),
        ('attention', 'Needs attention', Q(status__in=FAILURE_STATUSES) | Q(stage2_approval__state__in=STAGE2_FAILURES)),
        ('receipt', 'Waiting for BIR receipt', Q(stage2_approval__state='SUBMITTED_WAITING_FOR_CONFIRMATION', stage2_approval__receipt_check__received_at__isnull=True)),
        ('completed', 'Completed this month', Q(stage2_approval__receipt_check__finalized_at__date__gte=today.replace(day=1), stage2_approval__receipt_check__finalized_at__date__lte=today)),
    ]

def archive_blocker(order):
    if order.is_archived:
        return 'This filing is already archived.'
    if hasattr(order, 'stage2_approval'):
        return 'Filings with submission approvals cannot be archived here.'
    if order.status == 'PROCESSING_PREPARATION' or order.preparation_attempts.filter(state='RUNNING').exists():
        return 'Resolve the active run before archiving this filing.'
    return ''


def can_cancel_filing(user):
    return user.has_perm('workorders.change_workorder') or user.has_perms(
        ['workorders.view_prepared_pdf', 'automation_api.approve_stage2'])


def cancellation_blocker(order):
    reason = archive_blocker(order)
    if reason:
        return reason
    if order.status != 'AWAITING_SUBMISSION_APPROVAL':
        return 'Only filings awaiting submission approval can be cancelled.'
    return ''


@transaction.atomic
def cancel_order(*, actor, work_order_id, expected_version):
    from automation_api.cancellation import lock_execution, enqueue
    lock_execution()
    if not can_cancel_filing(actor):
        raise PermissionDenied('Filing edit or submission approval permission is required.')
    order = _load_current(work_order_id, expected_version)
    reason = cancellation_blocker(order)
    if reason:
        raise ValidationError(reason)
    previous = order.status
    order.status = 'CANCELLED'
    order.is_archived = True
    _persist(order, expected_version)
    enqueue(order)
    AuditEvent.objects.create(actor=actor, work_order=order, snapshot=order.current_snapshot,
        kind='STATUS_CHANGED', old_status=previous, new_status='CANCELLED',
        changed_fields=['status', 'is_archived'])
    return order

@transaction.atomic
def archive_order(*, actor, work_order_id, expected_version):
    require_permission(actor, 'workorders.change_workorder')
    require_permission(actor, 'automation_api.change_agent')
    order = _load_current(work_order_id, expected_version)
    reason = archive_blocker(order)
    if reason:
        raise ValidationError(reason)
    previous = order.status
    if order.status == 'READY_TO_PREPARE':
        order.status = 'DRAFT'
    order.is_archived = True
    _persist(order, expected_version)
    AuditEvent.objects.create(actor=actor, work_order=order, snapshot=order.current_snapshot,
        kind='STATUS_CHANGED', old_status=previous, new_status=order.status, changed_fields=['is_archived'])
    return order
