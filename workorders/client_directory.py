"""Read-only connection to the office client-files service."""
import json
import re
import uuid
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request

from django.conf import settings
from django.core.cache import cache


class DirectoryUnavailable(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(endpoint, params=None, *, limit=2_000_000):
    base = settings.CLIENT_FILES_URL
    parsed = urlsplit(base)
    allowed_hosts = getattr(settings, 'CLIENT_FILES_ALLOWED_HOSTS', {'127.0.0.1', 'localhost'})
    if (parsed.scheme != 'http' or parsed.hostname not in allowed_hosts
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise DirectoryUnavailable('Client directory connection is not configured.')
    url = base + endpoint + ('?' + urlencode(params) if params else '')
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=8) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Response too large')
        return data
    except (OSError, ValueError) as exc:
        raise DirectoryUnavailable('Client directory is unavailable. Check that the client-files app and office share are available, then retry.') from exc


def read_json(endpoint, params=None):
    try:
        value = json.loads(fetch(endpoint, params))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError) as exc:
        raise DirectoryUnavailable('Client directory returned an invalid response.') from exc


def _write(request, *, accepted=(200, 201)):
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=30) as response:
            if response.status not in accepted:
                raise DirectoryUnavailable('Client directory rejected the archive request.')
            return json.loads(response.read(2_000_001))
    except HTTPError as exc:
        if exc.code == 409:
            return {'exists': True}
        raise DirectoryUnavailable('Client directory could not save the final package.') from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise DirectoryUnavailable('Client directory could not save the final package.') from exc


def create_folder(parent, name):
    body = json.dumps({'parent': parent, 'name': name}).encode('utf-8')
    return _write(Request(settings.CLIENT_FILES_URL + '/api/folders', data=body, method='POST',
                          headers={'Content-Type': 'application/json'}))


def upload_pdf(folder, filename, data):
    return upload_file(folder, filename, data, content_type='application/pdf')


def upload_file(folder, filename, data, *, content_type):
    if content_type not in {'application/pdf', 'image/png'}:
        raise DirectoryUnavailable('Unsupported document type.')
    boundary = '----TaxAutomation' + uuid.uuid4().hex
    disposition = f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
    body = (f'--{boundary}\r\n{disposition}Content-Type: {content_type}\r\n\r\n'.encode('utf-8')
            + data + f'\r\n--{boundary}--\r\n'.encode('ascii'))
    url = settings.CLIENT_FILES_URL + '/api/upload?' + urlencode({'path': folder})
    return _write(Request(url, data=body, method='POST',
                          headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}))


def valid_name(name):
    return isinstance(name, str) and bool(name.strip()) and not name.startswith('.') and not any(c in name for c in '/\\\x00')


MONTH_NAMES = ('JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE',
               'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER')


def month_folder_name(month):
    if type(month) is not int or not 1 <= month <= 12:
        raise DirectoryUnavailable('A valid filing month is required for the package folder.')
    return f'{month:02d} {MONTH_NAMES[month - 1]}'


def archive_final_package(client, order, filename, data):
    """Archive packages under BIR/FILED RETURNS; monthly returns use year/month folders."""
    bir_folder = filing_folder(client, order)
    if bir_folder is None:
        return {'status': 'not_configured'}
    result = upload_pdf(bir_folder, filename, data)
    saved = result.get('saved') or []
    return {'status': 'saved', 'path': bir_folder, 'filename': saved[0].get('name', filename) if saved else filename}


def filing_folder(client, order):
    """Resolve the shared destination for prepared returns and final packages."""
    configured = (client.client_folder_path or '').strip().replace('\\', '/')
    if not configured:
        try:
            configured = client.registration_setup.folder
        except Exception:
            return None
    marker = re.search(r'/(?:CLIENT)/(.+)$', configured, re.I)
    relative = marker.group(1) if marker else configured.strip('/')
    parts = [part for part in relative.split('/') if part]
    if any(part in {'.', '..'} or ':' in part or '\x00' in part for part in parts):
        raise DirectoryUnavailable('The client folder path is invalid.')
    # Accept existing company, company/BIR, and legacy company/PERMANENT/BIR settings.
    if len(parts) >= 2 and [p.upper() for p in parts[-2:]] == ['PERMANENT', 'BIR']:
        parts = parts[:-2]
    elif parts and parts[-1].upper() in {'BIR', 'BIR FILING', 'FILED RETURNS'}:
        parts = parts[:-1]
    if len(parts) != 1 or not valid_name(parts[0]):
        raise DirectoryUnavailable('The client folder must identify one company under CLIENT.')
    company_folder = parts[0]
    listing = read_json('/api/browse', {'path': company_folder})
    entries = listing.get('entries')
    if not isinstance(entries, list):
        raise DirectoryUnavailable('Client directory returned an invalid folder list.')
    folders = [entry['name'] for entry in entries if isinstance(entry, dict)
               and entry.get('type') == 'folder' and valid_name(entry.get('name'))]
    destination = None
    for preferred in ('BIR', 'BIR FILING', 'FILED RETURNS'):
        matches = [name for name in folders if name.upper() == preferred]
        if len(matches) > 1:
            raise DirectoryUnavailable('Multiple matching archive folders require review.')
        if matches:
            destination = matches[0]
            break
    if destination is None:
        raise DirectoryUnavailable('No BIR, BIR FILING or FILED RETURNS folder exists in the company folder.')
    bir_folder = company_folder + '/' + destination
    if order is not None and order.filing_month is not None:
        month_name = month_folder_name(order.filing_month)
        year = str(order.filing_year)
        if not re.fullmatch(r'[0-9]{4}', year):
            raise DirectoryUnavailable('A four-digit filing year is required for the package folder.')
        create_folder(bir_folder, year)
        year_folder = bir_folder + '/' + year
        create_folder(year_folder, month_name)
        bir_folder = year_folder + '/' + month_name
    return bir_folder



def names():
    if not settings.CLIENT_FILES_URL:
        return []
    key = 'client-directory:' + settings.CLIENT_FILES_URL
    result = cache.get(key)
    if result is None:
        payload = read_json('/api/clients')
        if not isinstance(payload.get('clients'), list):
            raise DirectoryUnavailable('Client directory returned an invalid list.')
        result = sorted({n for n in payload['clients'] if valid_name(n)}, key=str.casefold)
        cache.set(key, result, 60)
    return result


def is_cor_candidate(filename):
    """Filter filenames, not parent folders; document contents still need review."""
    if not filename.lower().endswith('.pdf'):
        return False
    words = re.sub(r'[_\W]+', ' ', filename[:-4].casefold()).strip()
    if re.search(r'\b(?:0605|payment|payments|receipt|receipts|affidavit|application)\b', words):
        return False
    return bool(re.search(r'\b(?:2303|cor)\b|\bcertificate of registration\b', words))


def registration(client):
    if client not in names():
        from django.http import Http404
        raise Http404('Client folder not found.')
    payload = read_json('/api/client-registration', {'client': client})
    files = payload.get('files')
    if not isinstance(files, list):
        raise DirectoryUnavailable('Client directory returned an invalid file list.')
    checked = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = item.get('path', '')
        if not isinstance(path, str):
            continue
        parts = path.split('/')
        if len(parts) < 3 or parts[0] != client or any(p in {'', '.', '..'} or '\\' in p or ':' in p or '\x00' in p for p in parts):
            continue
        if is_cor_candidate(parts[-1]):
            checked.append({'name': parts[-1], 'path': path, 'folder': '/'.join(parts[:-1])})
    return {'files': checked, 'has_permanent': bool(payload.get('hasPermanent')),
            'incomplete': bool(payload.get('warnings'))}
