"""Copy review PDFs without making desktop success depend on the office share."""
import hashlib
from datetime import timedelta
from pathlib import PurePosixPath

from django.utils import timezone

from workorders import client_directory as directory
from .models import PreparedReturnArchive
from .worker_services import WorkerError, verify_stored_pdf


def enqueue(order):
    return PreparedReturnArchive.objects.get_or_create(
        work_order=order, defaults={'sha256': order.prepared_pdf_sha256})[0]


def prepared_filename(order):
    stem = PurePosixPath(order.review_pdf_filename).stem.removesuffix('_COMPLETE')
    # Distinguish separate work orders for the same client/form/period.
    return f'{stem}_PREPARED_{order.pk.hex}.pdf'


def copy_pdf(order, data, *, filename=None, content_type='application/pdf'):
    folder = directory.filing_folder(order.client, order)
    if folder is None:
        raise directory.DirectoryUnavailable('Set the client folder before saving the document.')
    filename = filename or prepared_filename(order)
    path = folder + '/' + filename
    listing = directory.read_json('/api/browse', {'path': folder})
    entries = listing.get('entries')
    if not isinstance(entries, list):
        raise directory.DirectoryUnavailable('Client directory returned an invalid folder list.')
    matches = [entry for entry in entries if isinstance(entry, dict)
               and str(entry.get('name', '')).casefold() == filename.casefold()]
    if matches:
        if len(matches) != 1 or matches[0].get('type') != 'file':
            raise WorkerError('archive_conflict', 'The document destination needs review.')
        existing = directory.fetch('/api/file', {'path': folder + '/' + matches[0]['name']}, limit=50_000_000)
        if hashlib.sha256(existing).digest() != hashlib.sha256(data).digest():
            raise WorkerError('archive_conflict', 'A different file already exists at the document destination.')
        return folder + '/' + matches[0]['name']
    if content_type == 'application/pdf':
        result = directory.upload_pdf(folder, filename, data)
    else:
        result = directory.upload_file(folder, filename, data, content_type=content_type)
    saved = result.get('saved') or []
    if not saved or saved[0].get('name') != filename:
        raise directory.DirectoryUnavailable('Document upload was not confirmed; it will be checked again.')
    # Verify the copy, also covering a lost acknowledgement on a previous run.
    existing = directory.fetch('/api/file', {'path': path}, limit=50_000_000)
    if hashlib.sha256(existing).digest() != hashlib.sha256(data).digest():
        raise WorkerError('archive_conflict', 'The saved document did not match its source.')
    return path


def process_pending(limit=20):
    ids = list(PreparedReturnArchive.objects.filter(
        state__in=['PENDING', 'RETRY'], next_attempt_at__lte=timezone.now()
    ).order_by('next_attempt_at').values_list('pk', flat=True)[:limit])
    saved = 0
    for pk in ids:
        # Claim with one short write; never hold a SQLite read transaction over network I/O.
        claimed = PreparedReturnArchive.objects.filter(
            pk=pk, state__in=['PENDING', 'RETRY'], next_attempt_at__lte=timezone.now()
        ).update(next_attempt_at=timezone.now() + timedelta(minutes=10))
        if not claimed:
            continue
        job = PreparedReturnArchive.objects.get(pk=pk)
        order = job.work_order
        try:
            if job.sha256 != order.prepared_pdf_sha256:
                raise WorkerError('pdf_changed', 'The prepared return changed; operator review is required.')
            data = verify_stored_pdf(order).read_bytes()
            if hashlib.sha256(data).hexdigest() != job.sha256:
                raise WorkerError('pdf_changed', 'The prepared return changed; operator review is required.')
            job.path = copy_pdf(order, data)
            job.state = 'SAVED'
            job.saved_at = timezone.now()
            job.error = ''
            saved += 1
        except WorkerError as exc:
            job.state = 'BLOCKED'
            job.error = str(exc)[:500]
        except (directory.DirectoryUnavailable, OSError) as exc:
            job.state = 'RETRY'
            job.error = str(exc)[:500]
            job.next_attempt_at = timezone.now() + timedelta(minutes=5)
        job.save()
    return saved
