"""Stage 2 rehearsal queue: actual submission is never authorized here."""
import secrets
import uuid
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from audit.models import AuditEvent
from workorders.models import WorkOrder
from workorders.services import require_permission
from .models import Stage2Approval, PreparationAttempt
from .worker_services import WorkerError, verify_stored_pdf, payload as preparation_payload, _active
from .worker_policy import LEASE_DURATION
from .views import endpoint, body

KEY = 'REVALIDATE_2551QV2018'
RESULTS = {'APPROVED_READY_TO_SUBMIT', 'BLOCKED_NOT_APPROVED', 'WORK_ORDER_VERIFICATION_FAILED',
           'SAVED_RETURN_NOT_UNIQUE', 'SAVED_RETURN_ROW_NOT_FOUND', 'FAILED_SYSTEM'}


def verify(approval):
    order = WorkOrder.objects.get(pk=approval.work_order_id)
    if (order.is_archived or order.status != 'AWAITING_SUBMISSION_APPROVAL'
            or order.current_snapshot_id != approval.snapshot_id
            or order.prepared_pdf_sha256 != approval.pdf_sha256):
        raise WorkerError('approval_changed', 'The approved return no longer matches. Operator review required.')
    verify_stored_pdf(order)
    return order


@transaction.atomic
def approve(*, actor, order_id, version, digest, comment=''):
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.view_prepared_pdf')
    order = WorkOrder.objects.select_for_update().get(pk=order_id)
    if order.version != version or order.prepared_pdf_sha256 != digest:
        raise ValidationError('The filing changed. Reload and review the PDF again.')
    existing = Stage2Approval.objects.filter(work_order=order).first()
    if existing:
        verify(existing)
        return existing
    approval = Stage2Approval(work_order=order, snapshot=order.current_snapshot,
                              approved_by=actor, pdf_sha256=digest, comment=comment)
    verify(approval)
    approval.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor,
                              kind='APPROVED', new_status='STAGE2_QUEUED')
    return approval


def payload(approval):
    attempt = approval.attempt
    if attempt.state != 'RUNNING':
        return {'AttemptId': str(attempt.pk), 'State': attempt.state, 'Status': approval.state}
    order = verify(approval)
    data = preparation_payload(attempt)
    prefix = f'/api/agent/stage2/{attempt.pk}'
    data.update(AutomationKey=KEY, ExpectedXmlPath=order.saved_xml_path,
                ExpectedPdfPath=order.prepared_pdf_vm_path, RenewUrl=prefix+'/renew/', ResultUrl=prefix+'/result/')
    data.pop('PdfUploadUrl', None)
    data['Inputs'].update(ApprovedForSubmission=True, SubmissionEnabled=False,
        WorkOrderId=order.work_order_id, ApprovalId=str(approval.pk),
        ApprovedBy=approval.approved_by.get_username(), ApprovedPdfSha256=approval.pdf_sha256)
    return data


@transaction.atomic
def claim_job(agent, request_id):
    _active(agent)
    existing = PreparationAttempt.objects.filter(pk=request_id).first()
    if existing:
        approval = Stage2Approval.objects.filter(attempt=existing).first()
        if not approval or existing.agent_id != agent.pk:
            raise WorkerError('request_conflict', 'This request belongs to another stage or worker.')
        if existing.state == 'RUNNING' and existing.lease_expires_at <= timezone.now():
            raise WorkerError('lease_expired', 'Operator recovery required; do not rerun Stage 2.')
        return approval
    if PreparationAttempt.objects.filter(execution_slot=1).exists():
        return None
    for approval in Stage2Approval.objects.filter(state='QUEUED', attempt__isnull=True).order_by('approved_at'):
        # XML and PDF live on the preparation worker, not on an arbitrary VM.
        if not PreparationAttempt.objects.filter(work_order=approval.work_order, state='SUCCEEDED', agent=agent).exists():
            continue
        verify(approval)
        attempt = PreparationAttempt(id=request_id, work_order=approval.work_order, snapshot=approval.snapshot,
                                     agent=agent, lease_expires_at=timezone.now()+LEASE_DURATION)
        attempt.save(_service_write=True, force_insert=True)
        approval.attempt=attempt
        approval.state='RUNNING'
        approval.save(_service_write=True)
        AuditEvent.objects.create(work_order=approval.work_order, snapshot=approval.snapshot,
                                  performed_by_agent=agent, kind='API_LEASE', new_status='STAGE2_RUNNING')
        return approval
    return None


def owned(agent, attempt_id, token, completed=False):
    _active(agent)
    approval = Stage2Approval.objects.select_related('attempt').filter(attempt_id=attempt_id, attempt__agent=agent).first()
    if not approval or not secrets.compare_digest(str(approval.attempt.lease_token), str(token)):
        raise WorkerError('invalid_lease', 'Stage 2 lease does not match.', 403)
    attempt=approval.attempt
    if completed and attempt.state in {'SUCCEEDED', 'FAILED'}:
        return approval
    if attempt.state != 'RUNNING' or attempt.lease_expires_at <= timezone.now():
        raise WorkerError('lease_expired', 'Operator recovery required; do not rerun Stage 2.')
    verify(approval)
    return approval


@endpoint('POST')
def claim(request, agent):
    data=body(request, {'request_id', 'automation_keys'})
    if data['automation_keys'] != [KEY]:
        raise WorkerError('unsupported_automation', 'Stage 2 supports revalidation only.', 400)
    approval=claim_job(agent, uuid.UUID(data['request_id']))
    return JsonResponse(payload(approval)) if approval else HttpResponse(status=204)


@endpoint('POST')
@transaction.atomic
def renew(request, agent, attempt_id):
    data=body(request, {'lease_token'})
    approval=owned(agent, attempt_id, data['lease_token'])
    approval.attempt.lease_expires_at=timezone.now()+LEASE_DURATION
    approval.attempt.save(_service_write=True)
    return JsonResponse({'LeaseExpiresAt': approval.attempt.lease_expires_at.isoformat()})


@endpoint('POST')
@transaction.atomic
def result(request, agent, attempt_id):
    data=body(request, {'lease_token', 'SubmissionStatus'})
    status=data['SubmissionStatus']
    if status not in RESULTS:
        raise WorkerError('invalid_status', 'Actual submission is not enabled.', 400)
    approval=owned(agent, attempt_id, data['lease_token'], completed=True)
    attempt=approval.attempt
    if attempt.state != 'RUNNING':
        if approval.state != status:
            raise WorkerError('result_conflict', 'A different result is already recorded.')
    else:
        approval.state=status
        approval.save(_service_write=True)
        attempt.state='SUCCEEDED' if status == 'APPROVED_READY_TO_SUBMIT' else 'FAILED'
        attempt.execution_slot=None
        attempt.completed_at=timezone.now()
        attempt.save(_service_write=True)
        AuditEvent.objects.create(work_order=approval.work_order, snapshot=approval.snapshot,
                                  performed_by_agent=agent, kind='PREPARATION_RESULT', new_status=status)
    return JsonResponse({'Status': approval.state, 'SubmissionEnabled': False})
