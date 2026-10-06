"""Archive cancelled XML only on its preparation worker, while desktop work is idle."""
import ntpath
import re
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from audit.models import AuditEvent
from workorders.models import WorkOrder
from .models import Agent, PreparationAttempt, CancellationCleanup
from .views import endpoint, body
from .worker_services import WorkerError, return_identity_fields


def lock_execution():
    # Shared with both claim paths. A cleanup and a desktop attempt cannot start together.
    list(Agent.objects.select_for_update().order_by('pk').values_list('pk', flat=True))


def cleanup_pending():
    return CancellationCleanup.objects.filter(state__in=['PENDING', 'RUNNING']).exists()


def enqueue(order):
    attempt = order.preparation_attempts.filter(state='SUCCEEDED', snapshot=order.current_snapshot,
                                               stage2_approval__isnull=True).order_by('-completed_at').first()
    if not attempt:
        raise ValidationError('No successful preparation worker is recorded; cancellation needs operator review.')
    job = CancellationCleanup(work_order=order, attempt=attempt, agent=attempt.agent)
    job.save(_service_write=True)
    return job


def conflict(job):
    order = job.work_order
    if order.status != 'CANCELLED' or not order.is_archived or hasattr(order, 'stage2_approval'):
        return 'Cancellation state changed; XML retained.'
    identity = {field: getattr(order, field) for field in return_identity_fields(order)}
    if WorkOrder.objects.filter(is_archived=False).exclude(pk=order.pk).filter(
            Q(**identity) | Q(saved_xml_path__iexact=order.saved_xml_path)).exists():
        return 'Another active filing uses this return identity or XML path; XML retained.'
    source = ntpath.normpath(order.saved_xml_path)
    if (ntpath.dirname(source).lower() != r'C:\eBIRForms\savefile'.lower()
            or ntpath.basename(source) != order.expected_saved_return_name + '.xml'):
        return 'Saved XML does not match the cancelled return; XML retained.'
    return ''


def payload(job):
    order = job.work_order
    return {'CleanupId': str(job.pk), 'WorkOrderId': order.work_order_id,
            'Source': order.saved_xml_path, 'Filename': order.expected_saved_return_name + '.xml',
            'PreparedAfter': job.attempt.started_at.isoformat(), 'CancelledAt': job.created_at.isoformat(),
            'ArchivePath': ntpath.join(r'C:\TaxAutomation\Archive\Cancelled', order.work_order_id,
                                     order.expected_saved_return_name + '.xml')}


@endpoint('POST')
@transaction.atomic
def claim(request, agent):
    body(request, set())
    lock_execution()
    if PreparationAttempt.objects.filter(state='RUNNING').exists():
        return HttpResponse(status=204)
    running = CancellationCleanup.objects.filter(state='RUNNING').first()
    if running:
        return JsonResponse(payload(running)) if running.agent_id == agent.pk else HttpResponse(status=204)
    job = CancellationCleanup.objects.select_for_update().filter(agent=agent, state='PENDING').order_by('created_at').first()
    if not job:
        return HttpResponse(status=204)
    reason = conflict(job)
    if reason:
        job.state = 'FAILED'; job.error = reason; job.save(_service_write=True)
        return HttpResponse(status=204)
    job.state = 'RUNNING'; job.save(_service_write=True)
    return JsonResponse(payload(job))


@endpoint('POST')
@transaction.atomic
def finish(request, agent, cleanup_id):
    data = body(request, {'Archived', 'ArchivePath', 'Sha256', 'Error'})
    lock_execution()
    job = CancellationCleanup.objects.select_for_update().filter(pk=cleanup_id, agent=agent).first()
    if not job:
        raise WorkerError('not_found', 'Cleanup does not belong to this worker.', 404)
    if type(data['Archived']) is not bool:
        raise WorkerError('invalid_result', 'Archived must be boolean.', 400)
    if data['Archived']:
        if (data['ArchivePath'] != payload(job)['ArchivePath']
                or not isinstance(data['Sha256'], str) or not re.fullmatch('[0-9a-f]{64}', data['Sha256'])):
            raise WorkerError('invalid_archive', 'Archive evidence does not match this cleanup.')
        if job.state == 'DONE' and job.sha256 == data['Sha256'] and job.archive_path == data['ArchivePath']:
            return JsonResponse({'Recorded': True})
    if job.state != 'RUNNING':
        raise WorkerError('invalid_state', 'Cleanup is not running.')
    job.state = 'DONE' if data['Archived'] else 'FAILED'
    job.error = '' if data['Archived'] else 'VM cleanup could not verify or move the XML. Files require operator review.'
    job.archive_path = data['ArchivePath'] if data['Archived'] else ''
    job.sha256 = data['Sha256'] if data['Archived'] else ''
    job.completed_at = timezone.now()
    job.save(_service_write=True)
    AuditEvent.objects.create(work_order=job.work_order, snapshot=job.work_order.current_snapshot,
        performed_by_agent=agent, kind='STATUS_CHANGED', old_status='CANCELLED',
        new_status='CANCELLED_XML_ARCHIVED' if data['Archived'] else 'CANCELLED_XML_CLEANUP_FAILED')
    return JsonResponse({'Recorded': True})
