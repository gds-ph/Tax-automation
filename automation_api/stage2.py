"""Snapshot-bound Stage 2 execution with separate live submission authorization."""
import secrets
import hashlib
import ntpath
import struct
from pathlib import Path
from django.conf import settings
import uuid
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse
from audit.models import AuditEvent
from workorders.models import WorkOrder
from workorders.services import require_permission
from .models import Stage2Approval, PreparationAttempt
from .worker_services import WorkerError, verify_stored_pdf, payload as preparation_payload, _active, return_identity_fields, valid_automation_keys
from .worker_policy import LEASE_DURATION
from .views import endpoint, body

KEY = 'REVALIDATE_2551QV2018'
LIVE_KEY = 'SUBMIT_2551QV2018'
MONTHLY_LIVE_KEY = 'SUBMIT_1601CV2018'
EQ_LIVE_KEY = 'SUBMIT_1601EQ'
F_LIVE_KEY = 'SUBMIT_0619F'
VT_LIVE_KEY = 'SUBMIT_1600VT'
SUPPORTED_KEYS = {KEY, LIVE_KEY, MONTHLY_LIVE_KEY, EQ_LIVE_KEY, F_LIVE_KEY, VT_LIVE_KEY}
SUCCESS = 'SUBMITTED_WAITING_FOR_CONFIRMATION'
LIVE_RESULTS = {SUCCESS, 'SUBMISSION_UNCONFIRMED', 'BLOCKED_NOT_APPROVED', 'WORK_ORDER_VERIFICATION_FAILED', 'SAVED_RETURN_NOT_UNIQUE', 'SAVED_RETURN_ROW_NOT_FOUND', 'FAILED_SYSTEM'}
RESULTS = {'APPROVED_READY_TO_SUBMIT', 'BLOCKED_NOT_APPROVED', 'WORK_ORDER_VERIFICATION_FAILED',
           'SAVED_RETURN_NOT_UNIQUE', 'SAVED_RETURN_ROW_NOT_FOUND', 'FAILED_SYSTEM'}


def automation_key(approval):
    number = approval.snapshot.data['form']['expected_form_number']
    if number == '1600VTv2018':
        if not approval.submission_enabled:
            raise WorkerError('unsupported_automation', '1600VT has no queued revalidation workflow.')
        return VT_LIVE_KEY
    if number == '0619F':
        if not approval.submission_enabled:
            raise WorkerError('unsupported_automation', '0619F has no queued revalidation workflow.')
        return F_LIVE_KEY
    if number == '1601EQ':
        if not approval.submission_enabled:
            raise WorkerError('unsupported_automation', '1601EQ has no queued revalidation workflow.')
        return EQ_LIVE_KEY
    if number == '1601Cv2018':
        if not approval.submission_enabled:
            raise WorkerError('unsupported_automation', '1601C has no queued revalidation workflow.')
        return MONTHLY_LIVE_KEY
    if number == '2551Qv2018':
        return LIVE_KEY if approval.submission_enabled else KEY
    raise WorkerError('unsupported_automation', 'Stage 2 is not implemented for this form.')


def verify(approval):
    order = WorkOrder.objects.get(pk=approval.work_order_id)
    if (order.is_archived or order.status != 'AWAITING_SUBMISSION_APPROVAL'
            or order.current_snapshot_id != approval.snapshot_id
            or order.prepared_pdf_sha256 != approval.pdf_sha256):
        raise WorkerError('approval_changed', 'The approved return no longer matches. Operator review required.')
    verify_stored_pdf(order)
    return order


@transaction.atomic
def approve(*, actor, order_id, version, digest, comment='', submission_enabled=False):
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.view_prepared_pdf')
    order = WorkOrder.objects.select_for_update().get(pk=order_id)
    if order.version != version or order.prepared_pdf_sha256 != digest:
        raise ValidationError('The filing changed. Reload and review the PDF again.')
    if submission_enabled and not order.live_submission_available:
        raise ValidationError('Live submission for this form is not enabled. Complete the worker integration first.')
    if order.expected_form_number in {'1601Cv2018', '1601EQ', '0619F', '1600VTv2018'} and not submission_enabled:
        raise ValidationError('Open-and-validate tests for this form run separately from the approval queue.')
    existing = Stage2Approval.objects.filter(work_order=order).first()
    if existing:
        verify(existing)
        if existing.submission_enabled != submission_enabled:
            raise ValidationError('An existing approval cannot be upgraded or rerun. Review its recorded execution first.')
        return existing
    if submission_enabled:
        identity = {f'work_order__{field}': getattr(order, field) for field in
                    return_identity_fields(order)}
        if Stage2Approval.objects.filter(Q(submission_enabled=True) | Q(state='MANUALLY_SUBMITTED_UNVERIFIED'), **identity).exclude(work_order=order).exists():
            raise ValidationError('This taxpayer and period already has a submission approval. Review that attempt; do not submit again.')
    approval = Stage2Approval(work_order=order, snapshot=order.current_snapshot,
                              approved_by=actor, pdf_sha256=digest, comment=comment, submission_enabled=submission_enabled)
    verify(approval)
    approval.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor,
                              kind='APPROVED', new_status='SUBMISSION_QUEUED' if submission_enabled else 'STAGE2_QUEUED')
    return approval


@transaction.atomic
def recover_before_submit(*, actor, approval_id, expected_attempt_id, confirmed_not_submitted, evidence_note):
    """Operator-only recovery; never infer non-submission from missing evidence."""
    require_permission(actor, 'automation_api.change_agent')
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.change_workorder')
    if confirmed_not_submitted is not True or not evidence_note.strip():
        raise ValidationError('Explicit stopped-before-submit confirmation and evidence are required.')
    approval = Stage2Approval.objects.select_for_update().get(pk=approval_id)
    if (approval.state != 'RUNNING' or not approval.submission_enabled
            or str(approval.attempt_id) != str(expected_attempt_id)
            or approval.success_screenshot or approval.success_screenshot_sha256):
        raise ValidationError('Attempt changed or submission evidence exists. Recovery refused.')
    attempt = PreparationAttempt.objects.select_for_update().get(pk=approval.attempt_id)
    if attempt.state != 'RUNNING' or attempt.result_digest:
        raise ValidationError('Only an unresolved, unreported attempt can be recovered this way.')
    order = verify(approval)
    attempt.state = 'ABANDONED'
    attempt.execution_slot = None
    attempt.completed_at = timezone.now()
    attempt.save(_service_write=True)
    approval.comment += (f'\nPre-submit recovery by {actor.get_username()} at {timezone.now().isoformat()}; '
                         f'preserved attempt {attempt.pk}: {evidence_note.strip()}')
    approval.attempt = None
    approval.state = 'QUEUED'
    approval.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=approval.snapshot, actor=actor,
        kind='ATTEMPT_ABANDONED', old_status='STAGE2_RUNNING', new_status='STAGE2_STOPPED_BEFORE_SUBMIT')
    AuditEvent.objects.create(work_order=order, snapshot=approval.snapshot, actor=actor,
        kind='STATUS_CHANGED', old_status='STAGE2_STOPPED_BEFORE_SUBMIT', new_status='SUBMISSION_QUEUED',
        changed_fields=['attempt', 'state', 'comment'])
    return approval


@transaction.atomic
def reconcile_manual_submission(*, actor, approval_id, expected_attempt_id, confirmed_submitted, evidence_note):
    """Close interrupted automation after operator-confirmed manual submission."""
    require_permission(actor, 'automation_api.change_agent')
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.change_workorder')
    if confirmed_submitted is not True or not evidence_note.strip():
        raise ValidationError('Explicit manual submission confirmation and evidence note are required.')
    approval = Stage2Approval.objects.select_for_update().get(pk=approval_id)
    if (str(approval.attempt_id) != str(expected_attempt_id) or not approval.submission_enabled
            or approval.success_screenshot or approval.success_screenshot_sha256):
        raise ValidationError('Attempt changed or recorded evidence requires separate review.')
    attempt = PreparationAttempt.objects.select_for_update().get(pk=approval.attempt_id)
    if approval.state == 'MANUALLY_SUBMITTED_UNVERIFIED' and attempt.state == 'ABANDONED':
        return approval
    if approval.state != 'RUNNING' or attempt.state != 'RUNNING' or attempt.result_digest:
        raise ValidationError('Only an interrupted, unreported live attempt can be reconciled.')
    order = verify(approval)
    attempt.state = 'ABANDONED'
    attempt.execution_slot = None
    attempt.completed_at = timezone.now()
    attempt.save(_service_write=True)
    approval.state = 'MANUALLY_SUBMITTED_UNVERIFIED'
    approval.comment += (f'\nManual submission reconciliation by {actor.get_username()} at '
                         f'{timezone.now().isoformat()}; preserved attempt {attempt.pk}: {evidence_note.strip()}')
    approval.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=approval.snapshot, actor=actor,
        kind='ATTEMPT_ABANDONED', old_status='STAGE2_RUNNING', new_status=approval.state)
    AuditEvent.objects.create(work_order=order, snapshot=approval.snapshot, actor=actor,
        kind='STATUS_CHANGED', old_status='STAGE2_RUNNING', new_status=approval.state,
        changed_fields=['state', 'comment'])
    return approval


@transaction.atomic
def retry_saved_return_lookup(*, actor, approval_id, expected_attempt_id, evidence_note):
    """Explicit operator retry of a reported failure before opening the return."""
    require_permission(actor, 'automation_api.change_agent')
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.change_workorder')
    if not evidence_note.strip():
        raise ValidationError('Evidence explaining the corrected lookup is required.')
    approval = Stage2Approval.objects.select_for_update().get(pk=approval_id)
    if (approval.state != 'SAVED_RETURN_ROW_NOT_FOUND' or not approval.submission_enabled
            or str(approval.attempt_id) != str(expected_attempt_id)
            or approval.success_screenshot or approval.success_screenshot_sha256):
        raise ValidationError('Only the specified failed saved-return lookup can be retried.')
    attempt = PreparationAttempt.objects.select_for_update().get(pk=approval.attempt_id)
    if attempt.state != 'FAILED' or attempt.execution_slot is not None or not attempt.completed_at:
        raise ValidationError('The failed lookup must be completed before retrying.')
    order = verify(approval)
    approval.comment += (f'\nSaved-return lookup retry by {actor.get_username()} at {timezone.now().isoformat()}; '
                         f'preserved failed attempt {attempt.pk}: {evidence_note.strip()}')
    approval.attempt = None
    approval.state = 'QUEUED'
    approval.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=approval.snapshot, actor=actor,
        kind='STATUS_CHANGED', old_status='SAVED_RETURN_ROW_NOT_FOUND', new_status='SUBMISSION_QUEUED',
        changed_fields=['attempt', 'state', 'comment'])
    return approval


def payload(approval):
    attempt = approval.attempt
    if attempt.state != 'RUNNING':
        return {'AttemptId': str(attempt.pk), 'State': attempt.state, 'Status': approval.state}
    order = verify(approval)
    data = preparation_payload(attempt)
    prefix = f'/api/agent/stage2/{attempt.pk}'
    data.update(AutomationKey=automation_key(approval), ExpectedXmlPath=order.saved_xml_path,
                ExpectedPdfPath=order.prepared_pdf_vm_path, RenewUrl=prefix+'/renew/', ResultUrl=prefix+'/result/')
    data.pop('PdfUploadUrl', None)
    data['Inputs'].update(ApprovedForSubmission=True, SubmissionEnabled=approval.submission_enabled,
        WorkOrderId=order.work_order_id, ApprovalId=str(approval.pk),
        ApprovedBy=approval.approved_by.get_username(), ApprovedPdfSha256=approval.pdf_sha256)
    data['Inputs'].update(ApprovedReturnPeriod=data['ExpectedReturnPeriod'],
                          ApprovedSavedReturnName=data['ExpectedSavedReturnName'],
                          ApprovedXmlPath=order.saved_xml_path)
    if approval.submission_enabled:
        data['ScreenshotUploadUrl'] = prefix + '/screenshot/'
        data['Inputs']['SuccessScreenshotPath'] = ntpath.join(data['Inputs']['OutputFolder'], 'submission-success.png')
    return data


@transaction.atomic
def claim_job(agent, request_id, automation_keys=None):
    from .cancellation import lock_execution, cleanup_pending
    lock_execution()
    automation_keys = automation_keys or [KEY]
    _active(agent)
    existing = PreparationAttempt.objects.filter(pk=request_id).first()
    if existing:
        approval = Stage2Approval.objects.filter(attempt=existing).first()
        if not approval or existing.agent_id != agent.pk:
            raise WorkerError('request_conflict', 'This request belongs to another stage or worker.')
        if automation_key(approval) not in automation_keys:
            raise WorkerError('unsupported_automation', 'Worker does not support this approval mode.')
        if existing.state == 'RUNNING' and existing.lease_expires_at <= timezone.now():
            raise WorkerError('lease_expired', 'Operator recovery required; do not rerun Stage 2.')
        return approval
    if cleanup_pending() or PreparationAttempt.objects.filter(execution_slot=1).exists():
        return None
    for approval in Stage2Approval.objects.filter(state='QUEUED', attempt__isnull=True,
                                                  work_order__is_archived=False).order_by('approved_at'):
        if automation_key(approval) not in automation_keys:
            continue
        if approval.submission_enabled and not approval.work_order.live_submission_available:
            continue
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
    if not valid_automation_keys(data['automation_keys'], SUPPORTED_KEYS):
        raise WorkerError('unsupported_automation', 'Advertise supported Stage 2 automation keys.', 400)
    approval=claim_job(agent, uuid.UUID(data['request_id']), data['automation_keys'])
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
    approval=owned(agent, attempt_id, data['lease_token'], completed=True)
    if status not in (LIVE_RESULTS if approval.submission_enabled else RESULTS):
        raise WorkerError('invalid_status', 'Result is not valid for this approval mode.', 400)
    if status == SUCCESS:
        screenshot_path(approval)  # Success requires durable, integrity-checked evidence.
    attempt=approval.attempt
    if attempt.state != 'RUNNING':
        if approval.state != status:
            raise WorkerError('result_conflict', 'A different result is already recorded.')
    else:
        approval.state=status
        approval.save(_service_write=True)
        attempt.state='SUCCEEDED' if status in {'APPROVED_READY_TO_SUBMIT', SUCCESS} else 'FAILED'
        attempt.execution_slot=None
        attempt.completed_at=timezone.now()
        attempt.save(_service_write=True)
        AuditEvent.objects.create(work_order=approval.work_order, snapshot=approval.snapshot,
                                  performed_by_agent=agent, kind='STATUS_CHANGED' if approval.submission_enabled else 'PREPARATION_RESULT', new_status=status)
    return JsonResponse({'Status': approval.state, 'SubmissionEnabled': approval.submission_enabled})


def screenshot_path(approval):
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / approval.success_screenshot).resolve()
    if (not approval.success_screenshot or not path.is_relative_to(root)
            or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != approval.success_screenshot_sha256):
        raise WorkerError('missing_evidence', 'The success screenshot is missing or failed its integrity check.')
    return path


@endpoint('PUT')
@transaction.atomic
def screenshot(request, agent, attempt_id):
    approval = owned(agent, attempt_id, request.headers.get('X-Lease-Token', ''), completed=True)
    if approval.attempt.state != 'RUNNING' and not approval.success_screenshot_sha256:
        raise WorkerError('attempt_finished', 'This attempt is already closed.')
    if not approval.submission_enabled:
        raise WorkerError('wrong_mode', 'This approval does not authorize submission.', 409)
    if request.content_type != 'image/png':
        raise WorkerError('content_type', 'Supply a PNG screenshot.', 415)
    data = request.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise WorkerError('too_large', 'Screenshot exceeds 10 MiB.', 413)
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise WorkerError('invalid_image', 'Invalid PNG screenshot.', 400)
    width, height = struct.unpack('>II', data[16:24])
    if not 1 <= width <= 20000 or not 1 <= height <= 20000:
        raise WorkerError('invalid_image', 'Invalid screenshot dimensions.', 400)
    digest = hashlib.sha256(data).hexdigest()
    if digest != request.headers.get('X-Screenshot-Sha256'):
        raise WorkerError('hash_mismatch', 'Screenshot hash mismatch.', 400)
    if approval.success_screenshot_sha256 and approval.success_screenshot_sha256 != digest:
        raise WorkerError('evidence_conflict', 'Different evidence is already recorded.')
    relative = f'stage2/{approval.pk}/{digest}.png'
    path = Path(settings.MEDIA_ROOT) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    approval.success_screenshot = relative
    approval.success_screenshot_sha256 = digest
    approval.save(_service_write=True)
    return JsonResponse({'Recorded': True, 'Sha256': digest})


@transaction.atomic
def record_manual_submission(*, actor, order_id, version, evidence_note):
    """Record operator-reported evidence without creating execution authorization."""
    require_permission(actor, 'automation_api.approve_stage2')
    require_permission(actor, 'workorders.view_prepared_pdf')
    order = WorkOrder.objects.select_for_update().get(pk=order_id)
    if order.version != version or not evidence_note.strip():
        raise ValidationError('Review the current work order and supply an evidence note.')
    existing = Stage2Approval.objects.filter(work_order=order).first()
    if existing:
        if existing.state == 'MANUALLY_SUBMITTED_UNVERIFIED':
            return existing
        raise ValidationError('An execution record already exists. Reconcile it before recording manual submission.')
    receipt = Stage2Approval(work_order=order, snapshot=order.current_snapshot,
        approved_by=actor, pdf_sha256=order.prepared_pdf_sha256, comment=evidence_note,
        submission_enabled=False, state='MANUALLY_SUBMITTED_UNVERIFIED')
    verify(receipt)
    receipt.save(_service_write=True)
    AuditEvent.objects.create(work_order=order, snapshot=order.current_snapshot, actor=actor,
        kind='STATUS_CHANGED', new_status='MANUALLY_SUBMITTED_UNVERIFIED')
    return receipt
