"""Select source CORs conservatively, using certificate dates, never filenames."""
import re
from datetime import datetime


def certificate_date(document):
    text = document['result'].get('transcript', '')
    values = re.findall(r'Date\s+OCN\s+Generated\s*:\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', text, re.I)
    dates = set()
    for value in values:
        try:
            dates.add(datetime.strptime(value.replace(',', ''), '%B %d %Y').date())
        except ValueError:
            return None
    return next(iter(dates)) if len(dates) == 1 else None


def identity(document):
    initial = document['result']['initial']
    segments = [initial.get(k, '') for k in ('tin1', 'tin2', 'tin3', 'tin4')]
    if [len(s) for s in segments] != [3, 3, 3, 5] or not all(s.isascii() and s.isdigit() for s in segments):
        return None
    name = re.sub(r'\W+', '', initial.get('registered_name', '').upper())
    return tuple(segments) + (name,) if name else None


def equivalent(documents):
    signatures = set()
    for document in documents:
        result = document['result']
        initial = result['initial']
        ocns = set(re.findall(r'\bOCN\s*:\s*([A-Z0-9]+)', result.get('transcript', ''), re.I))
        if len(ocns) != 1:
            return False
        signatures.add((next(iter(ocns)).upper(), initial.get('rdo_code'),
                        re.sub(r'\W+', '', initial.get('registered_address', '').upper()),
                        tuple(sorted({r['form_code'].strip().upper() for r in result['rows']}))))
    return len(signatures) == 1


def clarity(document):
    result = document['result']
    score = result.get('readability_score')
    score = score if type(score) is int and 0 <= score <= 100 else 0
    # Older scans lack a visual score; fewer uncertain readings are a fallback.
    uncertain = sum(bool(r.get('uncertain')) for r in result['rows'])
    missing = sum(not result['initial'].get(k) for k in ('registered_name', 'rdo_code', 'registered_address'))
    return (score, -missing, -uncertain, -result.get('transcript', '').count('\ufffd'))


def select_documents(scan):
    """Choose the latest dated certificate within each company folder."""
    documents = scan.documents
    if len(documents) <= 1:
        return documents, ''
    dated = [(certificate_date(d), d) for d in documents]
    known = [(date, d) for date, d in dated if date is not None]
    if known:
        latest = max(date for date, _ in known)
        candidates = [d for date, d in known if date == latest]
        # A reviewed copy breaks ties only; it cannot override a newer COR.
        selected = max(candidates, key=lambda d: (
            d['sha256'] == scan.preferred_sha256, clarity(d), d['sha256']))
        note = ('Showing the latest dated COR in this company folder '
                f'(Date OCN Generated: {latest:%d %b %Y}). Other copies remain available below.')
        if len(known) != len(documents):
            note += ' Copies without a readable OCN date were excluded from date comparison.'
        return [selected], note
    preferred = next((d for d in documents if d['sha256'] == scan.preferred_sha256), None)
    if preferred:
        return [preferred], scan.selection_note + ' No readable OCN date was found to verify the latest copy.'
    return documents, 'No readable OCN dates were found. Review the copies to identify the latest COR.'
