"""Read-only connection to the office client-files service."""
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler

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
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}
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


def valid_name(name):
    return isinstance(name, str) and bool(name.strip()) and not name.startswith('.') and not any(c in name for c in '/\\\x00')


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
