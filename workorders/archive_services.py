"""Retain stopped test evidence while releasing the filing for a fresh test."""
from django.core.exceptions import ValidationError
from django.db import transaction
from audit.models import AuditEvent
from automation_api.models import PreparationAttempt
from .catalog_services import require_permission
from .services import _load_current, _persist


@transaction.atomic
def archive_stopped_order(*, actor, work_order_id, expected_version, confirmed_stopped):
    require_permission(actor, 'workorders.change_workorder')
    require_permission(actor, 'automation_api.change_agent')
    if confirmed_stopped is not True:
        raise ValidationError('Confirm all desktop flows have stopped first.')
    order = _load_current(work_order_id, expected_version)
    if order.status == 'PROCESSING_PREPARATION' or PreparationAttempt.objects.filter(work_order=order, state='RUNNING').exists():
        raise ValidationError('Abandon the confirmed stopped attempt before archiving.')
    old_status = order.status
    if order.status == 'READY_TO_PREPARE':
        order.status = 'DRAFT'
    order.is_archived = True
    _persist(order, expected_version)
    AuditEvent.objects.create(actor=actor, work_order=order, snapshot=order.current_snapshot,
        kind='STATUS_CHANGED', old_status=old_status, new_status=order.status,
        changed_fields=['is_archived'])
    return order
