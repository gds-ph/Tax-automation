import hashlib
import uuid
from django.core.cache import cache
from django.core import signing
from django.urls import reverse
from . import client_directory as directory
from .cor_extraction import FORM_CATALOG, read_cor
from .models import RegistrationCardScan, FormDefinition
from .definitions import get_definition
from .cor_selection import select_documents


def scan_company(folder, refresh=False):
    scan, _ = RegistrationCardScan.objects.get_or_create(folder=folder)
    if not refresh and scan.status in {'READY', 'EMPTY'}:
        return scan
    scan.status = 'SCANNING'
    scan.save(update_fields=['status', 'updated_at'])
    documents = []
    try:
        listing = directory.registration(folder)
        previous = {d['sha256']: d['result'] for d in scan.documents}
        seen = set()
        for item in listing['files']:
            data = directory.fetch('/api/file', {'path': item['path']}, limit=20_000_000)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            result = previous.get(digest) or cache.get('cor-scan:v3:' + digest)
            if result is None:
                result = read_cor(data)
            documents.append({'path': item['path'], 'sha256': digest, 'result': result})
            # Save completed certificates even if the process is interrupted later.
            scan.documents = documents
            scan.save(update_fields=['documents', 'updated_at'])
        if listing.get('incomplete'):
            raise directory.DirectoryUnavailable('Incomplete directory search')
        scan.documents = documents
        scan.status = 'READY' if documents else 'EMPTY'
        scan.message = ''
    except Exception:
        scan.status = 'ERROR'
        scan.message = 'Registration scan could not finish. Saved cards remain available; retry the background scan.'
    scan.save()
    return scan


def registration_source_url(actor, folder, path):
    token = signing.dumps({'actor': actor.pk, 'client': folder, 'path': path}, salt='registration-file')
    return reverse('workorders:registration-file') + '?token=' + token


def card_actions(cards):
    available = {form.form_code: form for form in FormDefinition.objects.filter(
        is_active=True, preparation_automation_available=True) if get_definition(form.definition_key)}
    for card in cards:
        form = available.get(card['code'])
        card['can_prepare'] = bool(form)
        card['version'] = form.form_version if form else ''
    return cards


def saved_cards(scan, actor):
    groups = []
    documents, _ = select_documents(scan)
    for document in documents:
        result = document['result']
        draft = result | {'actor': actor.pk, 'folder': scan.folder,
                          'path': document['path'], 'sha256': document['sha256']}
        draft_id = uuid.uuid4()
        cache.set('cor-review:' + str(draft_id), draft, 3600)
        cards, seen = [], set()
        for row in result['rows']:
            code = row['form_code'].strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            title, frequency = FORM_CATALOG.get(code, (row['tax_type'] or 'Registration entry', row['frequency']))
            cards.append({'code': code, 'title': title, 'frequency': frequency,
                          'uncertain': row['uncertain'] or code not in result['initial']['filings']})
        groups.append({'draft': draft, 'draft_id': draft_id, 'cards': card_actions(cards), 'digest': document['sha256'],
                       'source_url': registration_source_url(actor, scan.folder, document['path'])})
    return groups
