"""Explicit advance authorization for one immutable filing snapshot."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from audit.models import AuditEvent
from workorders.catalog_services import require_permission
from .models import AutoSubmissionConsent


@transaction.atomic
def request_auto_approval(*, actor, order):
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.view_prepared_pdf')
    if not order.zero_filing:
        raise ValidationError('Non-zero returns require manual review of the prepared PDF.')
    if not order.live_submission_available:
        raise ValidationError('Live submission is not enabled for this form.')
    consent = AutoSubmissionConsent(work_order=order, snapshot=order.current_snapshot,
                                    requested_by=actor)
    consent.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot,
        actor=actor, kind='EDITED', changed_fields=['auto_submission_consent'])


@transaction.atomic
def apply_auto_approval(order):
    from .stage2 import approve
    from .worker_services import WorkerError
    consent = AutoSubmissionConsent.objects.select_for_update().select_related(
        'requested_by').filter(work_order=order, state='PENDING').first()
    if not consent:
        return
    try:
        with transaction.atomic():
            if order.status != 'AWAITING_SUBMISSION_APPROVAL':
                raise ValidationError('Preparation did not succeed. Manual review is required.')
            if consent.snapshot_id != order.current_snapshot_id:
                raise ValidationError('The filing changed after advance authorization. Review it again.')
            approve(actor=consent.requested_by, order_id=order.pk, version=order.version,
                digest=order.prepared_pdf_sha256, submission_enabled=True,
                comment=f'Automatic approval under advance authorization recorded {consent.requested_at.isoformat()}. No PDF review was asserted.')
    except (ValidationError, PermissionDenied, WorkerError) as exc:
        consent.state = 'BLOCKED'
        consent.reason = (' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))[:500]
    else:
        consent.state = 'APPLIED'
    consent.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=consent.snapshot,
        actor=consent.requested_by, kind='EDITED', new_status='AUTO_APPROVAL_' + consent.state,
        changed_fields=['auto_submission_consent_state', 'auto_submission_consent_reason'])
