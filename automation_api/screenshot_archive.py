"""Save verified submission screenshots beside prepared PDFs, including existing ones."""
import hashlib
from datetime import timedelta
from pathlib import PurePosixPath

from django.utils import timezone

from .models import Stage2Approval, SubmissionScreenshotArchive
from .prepared_archive import copy_pdf
from .stage2 import screenshot_path
from .worker_services import WorkerError
from workorders.client_directory import DirectoryUnavailable


def screenshot_filename(order):
    stem = PurePosixPath(order.review_pdf_filename).stem.removesuffix('_COMPLETE')
    return f'{stem}_SUBMISSION_SCREENSHOT_{order.pk.hex}.png'


def process_pending(limit=20):
    approvals = Stage2Approval.objects.filter(
        state__in=['SUBMITTED_WAITING_FOR_CONFIRMATION', 'BIR_RECEIPT_CONFIRMED'],
        work_order__submission_screenshot_archive__isnull=True,
        work_order__is_archived=False,
    ).exclude(success_screenshot='').exclude(success_screenshot_sha256='')
    for approval in approvals.iterator():
        SubmissionScreenshotArchive.objects.get_or_create(
            work_order_id=approval.work_order_id,
            defaults={'sha256': approval.success_screenshot_sha256})
    ids = list(SubmissionScreenshotArchive.objects.filter(
        state__in=['PENDING', 'RETRY'], next_attempt_at__lte=timezone.now()
    ).order_by('next_attempt_at').values_list('pk', flat=True)[:limit])
    saved = 0
    for pk in ids:
        # Claim with one short write; never hold a SQLite read transaction over network I/O.
        claimed = SubmissionScreenshotArchive.objects.filter(
            pk=pk, state__in=['PENDING', 'RETRY'], next_attempt_at__lte=timezone.now()
        ).update(next_attempt_at=timezone.now() + timedelta(minutes=10))
        if not claimed:
            continue
        job = SubmissionScreenshotArchive.objects.get(pk=pk)
        try:
            approval = Stage2Approval.objects.get(work_order=job.work_order)
            if approval.success_screenshot_sha256 != job.sha256:
                raise WorkerError('evidence_changed', 'The screenshot changed; operator review is required.')
            data = screenshot_path(approval).read_bytes()
            if hashlib.sha256(data).hexdigest() != job.sha256:
                raise WorkerError('evidence_changed', 'The screenshot changed; operator review is required.')
            job.path = copy_pdf(job.work_order, data, filename=screenshot_filename(job.work_order),
                                content_type='image/png')
            job.state = 'SAVED'
            job.saved_at = timezone.now()
            job.error = ''
            saved += 1
        except WorkerError as exc:
            job.state = 'BLOCKED'
            job.error = str(exc)[:500]
        except (DirectoryUnavailable, OSError) as exc:
            job.state = 'RETRY'
            job.error = str(exc)[:500]
            job.next_attempt_at = timezone.now() + timedelta(minutes=5)
        job.save()
    return saved
