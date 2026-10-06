"""Activity milestones derived from durable receipt and archive evidence."""
from types import SimpleNamespace
from django.utils.dateparse import parse_datetime


def receipt_activity(receipt):
    if receipt is None:
        return []
    rows = []
    def add(title, at, description):
        rows.append(SimpleNamespace(get_kind_display=title, created_at=at,
            description=description, old_status='', new_status='', changed_fields=[]))
    if receipt.received_at:
        add('BIR receipt received', receipt.received_at,
            'TRRC email timestamp for the matched return: ' + receipt.filename)
    if receipt.finalized_at and receipt.final_package:
        add('Final package created', receipt.finalized_at, receipt.final_package)
        archive = (receipt.evidence or {}).get('client_archive') or {}
        if archive.get('status') == 'saved':
            at = parse_datetime(archive.get('saved_at', '')) or receipt.finalized_at
            description = 'Folder: ' + archive.get('path', '') + ' | File: ' + archive.get('filename', '')
            if not archive.get('saved_at'):
                description += ' (Time shown is package completion; separate folder-copy time was not recorded.)'
            add('Final package saved to company folder', at, description)
        elif archive.get('status') == 'failed':
            add('Company folder copy failed', receipt.finalized_at,
                'The final package was created, but saving it to the company folder failed.')
        elif archive.get('status') == 'not_configured':
            add('Company folder copy not configured', receipt.finalized_at,
                'The final package is available in Documents; no company folder copy was recorded.')
    return rows
