"""Stage 1 leasing and result services. No desktop execution or submission."""
import hashlib
import json
import ntpath
import secrets
import tempfile
import uuid
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader
from audit.models import AuditEvent
from workorders.models import WorkOrder
from workorders.services import validate_readiness, _persist, require_permission
from workorders.validators import safe_filename_component
from .models import Agent, PreparationAttempt
from .worker_policy import LEASE_DURATION, MAX_PDF_BYTES, FAILURE_STATUSES, VM_WORKING_ROOT, VM_XML_ROOT


class WorkerError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def allowed_pdf_page_counts(order):
    """Return the physical page counts accepted for this form's prepared PDF."""
    form_number = order.current_snapshot.data['form']['expected_form_number']
    if form_number in {'1601EQ', '0619F', '1600VTv2018'}:
        return {1}
    if form_number == '1601Cv2018':
        # The Windows print path can split the form's second logical page into
        # two physical pages; both 2-page and 3-page outputs are valid.
        return {2, 3}
    return {2}


def _active(agent):
    if not Agent.objects.filter(pk=agent.pk, is_active=True).exists():
        raise WorkerError('unauthorized', 'The worker is disabled.', 401)


def payload(attempt):
    order = attempt.work_order
    if attempt.state != PreparationAttempt.State.RUNNING:
        return {'AttemptId': str(attempt.pk), 'WorkOrderId': order.work_order_id, 'State': attempt.state, 'Status': order.status}
    data = attempt.snapshot.data
    client, form, profile, filing = (data[key] for key in ('client', 'form', 'profile', 'filing'))
    inputs = {dest: str(client[source]) for dest, source in {
        'TIN1':'tin1', 'TIN2':'tin2', 'TIN3':'tin3', 'TIN4':'tin4', 'RDOCode':'rdo_code',
        'RegisteredName':'registered_name', 'RegisteredAddress':'registered_address', 'ZipCode':'zip_code',
        'TelephoneNumber':'telephone_number', 'EmailAddress':'email_address', 'LineOfBusiness':'line_of_business',
    }.items()}
    inputs.update({dest: form[source] for dest, source in {'FormSelectionText':'form_selection_text','FormCode':'form_code','ExpectedFormNumber':'expected_form_number'}.items()})
    inputs.update(FilingYear=filing['filing_year'], FilingQuarter=str(filing['filing_quarter'] or ''), YearEndMonth=profile['year_end_month'],
        ATCCode=filing['form_data'].get('atc_code', ''), ClientNameSafe=safe_filename_component(client['trade_name'] or client['registered_name']),
        OutputFolder=ntpath.join(VM_WORKING_ROOT, order.work_order_id, str(attempt.pk)))
    period=inputs['YearEndMonth']+inputs['FilingYear']+'Q'+inputs['FilingQuarter']
    name=''.join(inputs[key] for key in ('TIN1','TIN2','TIN3','TIN4'))+'-'+inputs['ExpectedFormNumber']+'-'+period
    pdf=f"{inputs['ClientNameSafe']}_{inputs['FormCode']}_{inputs['FilingYear']}_Q{inputs['FilingQuarter']}_COMPLETE.pdf"
    if form['filing_frequency'] == 'MONTHLY':
        inputs['FilingMonth'] = f"{filing['filing_month']:02d}"
        period = inputs['FilingMonth'] + inputs['FilingYear']
        name = ''.join(inputs[key] for key in ('TIN1','TIN2','TIN3','TIN4'))+'-'+inputs['ExpectedFormNumber']+'-'+period
        pdf = f"{inputs['ClientNameSafe']}_{inputs['FormCode']}_{inputs['FilingYear']}_{inputs['FilingMonth']}_COMPLETE.pdf"
    if form['expected_form_number'] == '0619F':
        name += 'WB'
    if form['expected_form_number'] == '1601EQ':
        inputs['FilingMonth'] = ''
        period = inputs['FilingYear'] + 'Q' + inputs['FilingQuarter']
        name = ''.join(inputs[key] for key in ('TIN1','TIN2','TIN3','TIN4')) + '-1601EQ-' + period
    prefix=f'/api/agent/preparation/{attempt.pk}'
    return {'AttemptId':str(attempt.pk), 'WorkOrderId':order.work_order_id, 'State':attempt.state, 'Status':order.status,
        'AutomationKey':form['automation_key'], 'LeaseToken':str(attempt.lease_token), 'LeaseExpiresAt':attempt.lease_expires_at.isoformat(),
        'SnapshotSha256':attempt.snapshot.sha256, 'Inputs':inputs, 'ExpectedReturnPeriod':period,
        'ExpectedSavedReturnName':name, 'ExpectedXmlPath':ntpath.join(VM_XML_ROOT,name+'.xml'),
        'ExpectedPdfPath':ntpath.join(inputs['OutputFolder'],pdf),
        'PdfUploadUrl':prefix+'/pdf/', 'ResultUrl':prefix+'/result/', 'RenewUrl':prefix+'/renew/'}


def valid_automation_keys(keys, allowed):
    return (isinstance(keys, list) and bool(keys) and all(isinstance(key, str) for key in keys)
            and len(set(keys)) == len(keys) and set(keys) <= allowed)


def return_identity_fields(order):
    fields = ('tin1', 'tin2', 'tin3', 'tin4', 'expected_form_number', 'filing_year')
    if order.expected_form_number == '1601EQ':
        return fields + ('filing_quarter',)
    return fields + (('filing_month',) if order.filing_month is not None else ('year_end_month', 'filing_quarter'))


def xml_reserved(order):
    """A reviewed XML must not be overwritten by another preparation of its name."""
    fields=return_identity_fields(order)
    return WorkOrder.objects.filter(is_archived=False, status="AWAITING_SUBMISSION_APPROVAL", **{field:getattr(order,field) for field in fields}).exclude(pk=order.pk).exists()


@transaction.atomic
def claim(*, agent, request_id, automation_keys):
    _active(agent)
    from .cancellation import lock_execution, cleanup_pending
    lock_execution()
    if not valid_automation_keys(automation_keys, {'PREPARE_2551QV2018_ZERO', 'PREPARE_1601CV2018_ZERO', 'PREPARE_1601EQ_ZERO', 'PREPARE_0619F_ZERO', 'PREPARE_1600VT_ZERO'}):
        raise WorkerError('unsupported_automation', 'Advertise supported preparation automation keys.', 400)
    existing=PreparationAttempt.objects.select_related('work_order','snapshot').filter(pk=request_id).first()
    if existing:
        if hasattr(existing, 'stage2_approval'):
            raise WorkerError('wrong_stage', 'This request belongs to Stage 2.')
        if existing.agent_id != agent.pk:
            raise WorkerError('request_conflict','This request ID belongs to another worker.')
        if existing.snapshot.data['form']['automation_key'] not in automation_keys:
            raise WorkerError('unsupported_automation', 'Worker no longer advertises this form.')
        if existing.state == 'RUNNING' and existing.lease_expires_at <= timezone.now():
            raise WorkerError('lease_expired','The lease expired. Stop and request operator review; do not rerun the desktop flow.')
        return existing
    if cleanup_pending():
        return None
    # One global desktop execution slot. Expiry never implies a desktop flow stopped.
    active_attempt = PreparationAttempt.objects.filter(execution_slot=1).first()
    if active_attempt:
        # The parent polls preparation before Stage 2. Let its owning worker
        # reach Stage 2's journal/replay checks without creating another task.
        if (active_attempt.agent_id == agent.pk
                and hasattr(active_attempt, 'stage2_approval')
                and active_attempt.lease_expires_at > timezone.now()):
            return None
        raise WorkerError('worker_busy','An attempt is already running or awaiting operator recovery. Do not start another flow.')
    for order in WorkOrder.objects.filter(is_archived=False, status='READY_TO_PREPARE').order_by('created_at','id').iterator(chunk_size=100):
        try:
            key=validate_readiness(order)
            order.full_clean()
        except ValidationError:
            continue
        if key not in automation_keys:
            continue
        now=timezone.now()
        attempt=PreparationAttempt(id=request_id,work_order=order,snapshot=order.current_snapshot,agent=agent,
                                   lease_expires_at=now+LEASE_DURATION)
        attempt.save(_service_write=True,force_insert=True)
        version=order.version
        order.status='PROCESSING_PREPARATION'
        order.lease_token=attempt.lease_token
        order.leased_at=now
        order.lease_expires_at=attempt.lease_expires_at
        order.agent_name=agent.name
        order.attempt_count+=1
        _persist(order,version)
        AuditEvent.objects.create(work_order=order,snapshot=order.current_snapshot,performed_by_agent=agent,
            kind='API_LEASE',old_status='READY_TO_PREPARE',new_status=order.status)
        return attempt
    return None


def owned_attempt(agent, attempt_id, lease_token, *, allow_completed=False):
    _active(agent)
    attempt=PreparationAttempt.objects.select_related('work_order','snapshot').filter(pk=attempt_id,agent=agent).first()
    if attempt and hasattr(attempt, 'stage2_approval'):
        raise WorkerError('wrong_stage', 'Use the Stage 2 endpoint.')
    if not attempt:
        raise WorkerError('not_found','Attempt not found.',404)
    if not secrets.compare_digest(str(attempt.lease_token),str(lease_token)):
        raise WorkerError('invalid_lease','The lease token does not match.',403)
    if allow_completed and attempt.state in {'SUCCEEDED','FAILED'}:
        return attempt
    if attempt.state != 'RUNNING' or attempt.lease_expires_at <= timezone.now():
        raise WorkerError('lease_expired','The attempt is finished or expired. Do not rerun it; request operator review.')
    if attempt.work_order.status != 'PROCESSING_PREPARATION' or attempt.work_order.current_snapshot_id != attempt.snapshot_id:
        raise WorkerError('work_order_changed','The claimed work order no longer matches the attempt.')
    return attempt


@transaction.atomic
def renew(*,agent,attempt_id,lease_token):
    attempt=owned_attempt(agent,attempt_id,lease_token)
    attempt.lease_expires_at=timezone.now()+LEASE_DURATION
    attempt.save(_service_write=True)
    order=attempt.work_order
    order.lease_expires_at=attempt.lease_expires_at
    _persist(order,order.version)
    AuditEvent.objects.create(work_order=order,snapshot=attempt.snapshot,performed_by_agent=agent,kind='LEASE_RENEWED')
    return attempt


def private_pdf_path(order):
    root=Path(settings.MEDIA_ROOT).resolve()
    path=(root/order.prepared_pdf.name).resolve()
    if not order.prepared_pdf.name or not path.is_relative_to(root) or path == root:
        raise WorkerError('invalid_storage','The stored PDF location is invalid.')
    return path


def verify_stored_pdf(order):
    path=private_pdf_path(order)
    try:
        with path.open('rb') as source:
            digest=hashlib.file_digest(source,'sha256').hexdigest()
    except OSError:
        raise WorkerError('pdf_missing','The protected PDF is missing. Operator review is required.') from None
    if not secrets.compare_digest(digest,order.prepared_pdf_sha256):
        raise WorkerError('pdf_changed','The protected PDF hash no longer matches. Operator review is required.')
    return path


def upload_pdf(*,agent,attempt_id,lease_token,source,expected_sha256):
    # Authentication/ownership is checked before reading the file and again at commit.
    attempt = owned_attempt(agent,attempt_id,lease_token,allow_completed=True)
    allowed_pages = allowed_pdf_page_counts(attempt.work_order)
    if not isinstance(expected_sha256,str) or len(expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise WorkerError('invalid_hash','Supply X-PDF-SHA256 as 64 lowercase hexadecimal characters.',400)
    stored_name=None
    try:
        with tempfile.SpooledTemporaryFile(max_size=2*1024*1024) as temporary:
            total=0; digest=hashlib.sha256()
            while True:
                chunk=source.read(min(64*1024,MAX_PDF_BYTES-total+1))
                if not chunk: break
                total+=len(chunk)
                if total>MAX_PDF_BYTES:
                    raise WorkerError('file_too_large','PDF exceeds the 25 MiB limit.',413)
                digest.update(chunk);temporary.write(chunk)
            if digest.hexdigest()!=expected_sha256:
                raise WorkerError('hash_mismatch','The PDF bytes do not match the supplied hash.',400)
            temporary.seek(0)
            if temporary.read(5)!=b'%PDF-':
                raise WorkerError('invalid_pdf','Upload the merged PDF.',400)
            temporary.seek(0)
            try:
                reader=PdfReader(temporary,strict=True)
                if reader.is_encrypted or len(reader.pages) not in allowed_pages:
                    raise ValueError('Unexpected page count')
                root=reader.root_object
                names=root.get('/Names',{})
                if hasattr(names,'get_object'): names=names.get_object()
                if any(key in root for key in ('/OpenAction','/AA')) or any(key in names for key in ('/JavaScript','/EmbeddedFiles')):
                    raise ValueError('Active content is not supported')
            except Exception:
                counts = ', '.join(str(count) for count in sorted(allowed_pages))
                raise WorkerError('invalid_pdf',f'The file must be a readable, unencrypted PDF with {counts} physical pages and no embedded actions or attachments.',400) from None
            temporary.seek(0)
            with transaction.atomic():
                attempt=owned_attempt(agent,attempt_id,lease_token,allow_completed=True)
                order=attempt.work_order
                if order.prepared_pdf:
                    if order.prepared_pdf_sha256!=expected_sha256:
                        raise WorkerError('pdf_conflict','A different PDF is already recorded for this attempt.')
                    verify_stored_pdf(order)
                    return order.prepared_pdf_sha256
                if attempt.state!='RUNNING':
                    raise WorkerError('attempt_finished','Cannot add files after an attempt finishes.')
                stored_name=default_storage.save(f'work_orders/{order.pk}/{attempt.pk}/{uuid.uuid4().hex}.pdf',File(temporary))
                order.prepared_pdf=stored_name
                order.prepared_pdf_sha256=expected_sha256
                verify_stored_pdf(order)
                _persist(order,order.version)
                AuditEvent.objects.create(work_order=order,snapshot=attempt.snapshot,performed_by_agent=agent,kind='PDF_UPLOADED',changed_fields=['prepared_pdf','prepared_pdf_sha256'])
            return expected_sha256
    except BaseException:
        # The filename is server-generated and only this request owns it.
        if stored_name:
            default_storage.delete(stored_name)
        raise


@transaction.atomic
def record_result(*,agent,attempt_id,lease_token,data):
    attempt=owned_attempt(agent,attempt_id,lease_token,allow_completed=True)
    allowed={'PreparationStatusOutput','PreparedPdfPath','SavedXmlPath'}
    if not isinstance(data,dict) or set(data)-allowed or any(not isinstance(value,str) or len(value)>500 for value in data.values()):
        raise WorkerError('invalid_result','Supply only the three Stage 1 output text fields.',400)
    state=data.get('PreparationStatusOutput')
    if state not in FAILURE_STATUSES | {'AWAITING_SUBMISSION_APPROVAL'}:
        raise WorkerError('invalid_status','This Stage 1 result status is not supported.',400)
    result_digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    order=attempt.work_order
    if attempt.state!='RUNNING':
        if attempt.result_digest==result_digest:
            return order
        raise WorkerError('result_conflict','A different final result was already recorded.')
    if state=='AWAITING_SUBMISSION_APPROVAL':
        expected=payload(attempt)
        for field,key in (('PreparedPdfPath','ExpectedPdfPath'),('SavedXmlPath','ExpectedXmlPath')):
            # Deliberately require a canonical exact VM path, no traversal/UNC/alternate streams.
            if data.get(field)!=expected[key]:
                raise WorkerError('path_mismatch',f'{field} must match the expected path supplied with the claim.',400)
        if not order.prepared_pdf or not order.prepared_pdf_sha256:
            raise WorkerError('pdf_required','Upload and verify the merged PDF before reporting success.')
        verify_stored_pdf(order)
        order.saved_xml_path=data['SavedXmlPath']
        order.prepared_pdf_vm_path=data['PreparedPdfPath']
        attempt.state='SUCCEEDED'
    else:
        if data.get('PreparedPdfPath') or data.get('SavedXmlPath'):
            raise WorkerError('invalid_result','Failure reports must leave both output paths empty.',400)
        attempt.state='FAILED'
        order.error_code=state
    order.preparation_status_output=state
    order.status=state
    _persist(order,order.version)
    attempt.completed_at=timezone.now()
    attempt.execution_slot=None
    attempt.result_digest=result_digest
    attempt.save(_service_write=True)
    AuditEvent.objects.create(work_order=order,snapshot=attempt.snapshot,performed_by_agent=agent,kind='PREPARATION_RESULT',
        old_status='PROCESSING_PREPARATION',new_status=state,changed_fields=['preparation_status_output','saved_xml_path','prepared_pdf_vm_path'])
    if state == 'AWAITING_SUBMISSION_APPROVAL':
        from .prepared_archive import enqueue
        enqueue(order)
    return order


@transaction.atomic
def abandon(*,actor,attempt_id,expected_version,confirmed_stopped):
    require_permission(actor,'automation_api.change_agent')
    require_permission(actor,'workorders.change_workorder')
    if confirmed_stopped is not True:
        raise ValidationError('Confirm the desktop flow has actually stopped before releasing its execution slot.')
    attempt=PreparationAttempt.objects.select_related('work_order').get(pk=attempt_id)
    order=attempt.work_order
    if attempt.state!='RUNNING' or order.version!=expected_version:
        raise ValidationError('The attempt changed. Reload before recovering it.')
    if hasattr(attempt, 'stage2_approval'):
        approval = attempt.stage2_approval
        approval.state = 'ABANDONED'
        approval.save(_service_write=True)
        attempt.state='ABANDONED';attempt.execution_slot=None;attempt.completed_at=timezone.now()
        attempt.save(_service_write=True)
        AuditEvent.objects.create(work_order=order,snapshot=attempt.snapshot,actor=actor,
            kind='ATTEMPT_ABANDONED',old_status='STAGE2_RUNNING',new_status='STAGE2_ABANDONED')
        return order
    order.status='FAILED_SYSTEM';order.error_code='OPERATOR_STOPPED';order.preparation_status_output='FAILED_SYSTEM'
    _persist(order,expected_version)
    attempt.state='ABANDONED';attempt.execution_slot=None;attempt.completed_at=timezone.now()
    attempt.save(_service_write=True)
    AuditEvent.objects.create(work_order=order,snapshot=attempt.snapshot,actor=actor,kind='ATTEMPT_ABANDONED',
        old_status='PROCESSING_PREPARATION',new_status=order.status)
    return order


def preparation_recovery(*, agent, attempt_id, lease_token, work_order_id, automation_key):
    """Read-only permission to retire one journal after explicit operator release."""
    _active(agent)
    attempt = PreparationAttempt.objects.select_related('work_order', 'snapshot').filter(
        pk=attempt_id, agent=agent).first()
    if not attempt or not secrets.compare_digest(str(attempt.lease_token), str(lease_token)):
        raise WorkerError('invalid_attempt', 'The journal does not match this worker attempt.', 403)
    if (hasattr(attempt, 'stage2_approval') or
            work_order_id != attempt.work_order.work_order_id or
            automation_key != attempt.snapshot.data['form']['automation_key'] or
            not automation_key.startswith('PREPARE_')):
        raise WorkerError('wrong_stage', 'Only the matching preparation journal can be recovered.', 409)
    released = (attempt.state == 'ABANDONED' and attempt.execution_slot is None and
                attempt.completed_at is not None)
    return {'ClearPending': released, 'AttemptId': str(attempt.pk),
            'WorkOrderId': work_order_id, 'AutomationKey': automation_key}
