"""Read-only Gmail OAuth and receipt lookup used by the dashboard itself."""
import base64, email, imaplib, json, re, urllib.parse, urllib.request, urllib.error
from html import unescape
from django.utils.html import strip_tags
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings
from .models import GmailMailbox

API='https://gmail.googleapis.com/gmail/v1/users/me'
TOKEN_PATH=Path(settings.GMAIL_TOKEN_FILE)
_access={'token':'','expires':0}

def exchange(code):
    data=urllib.parse.urlencode({'code':code,'client_id':settings.GMAIL_CLIENT_ID,'client_secret':settings.GMAIL_CLIENT_SECRET,'redirect_uri':settings.GMAIL_REDIRECT_URI,'grant_type':'authorization_code'}).encode()
    req=urllib.request.Request('https://oauth2.googleapis.com/token',data=data,method='POST')
    with urllib.request.urlopen(req,timeout=30) as response: result=json.loads(response.read())
    if not result.get('refresh_token'): raise RuntimeError('Google returned no refresh token.')
    TOKEN_PATH.parent.mkdir(parents=True,exist_ok=True); TOKEN_PATH.write_text(json.dumps({'refresh_token':result['refresh_token']}),encoding='utf-8'); TOKEN_PATH.chmod(0o600)

def _token():
    try: return json.loads(TOKEN_PATH.read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}

def _access_token():
    now=int(datetime.now(timezone.utc).timestamp())
    if _access['token'] and now < _access['expires']-60: return _access['token']
    refresh=settings.GMAIL_REFRESH_TOKEN or _token().get('refresh_token')
    if not refresh: raise RuntimeError('Gmail is not connected.')
    data=urllib.parse.urlencode({'client_id':settings.GMAIL_CLIENT_ID,'client_secret':settings.GMAIL_CLIENT_SECRET,'refresh_token':refresh,'grant_type':'refresh_token'}).encode()
    try:
        req=urllib.request.Request('https://oauth2.googleapis.com/token',data=data,method='POST')
        with urllib.request.urlopen(req,timeout=30) as response: result=json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 400: TOKEN_PATH.unlink(missing_ok=True)
        raise RuntimeError('Gmail authorization expired. Connect Gmail again.') from error
    _access.update(token=result['access_token'],expires=now+int(result.get('expires_in',3600))); return _access['token']

def _get(path,params):
    req=urllib.request.Request(API+path+'?'+urllib.parse.urlencode(params),headers={'Authorization':'Bearer '+_access_token()})
    with urllib.request.urlopen(req,timeout=60) as response: return json.loads(response.read())

def _text(part):
    if part.get('mimeType')=='text/plain' and part.get('body',{}).get('data'):
        return base64.urlsafe_b64decode(part['body']['data']+'===').decode('utf-8','replace')
    return ''.join(_text(child) for child in part.get('parts',[]))

def _html(part):
    if part.get('mimeType') == 'text/html' and part.get('body',{}).get('data'):
        return base64.urlsafe_b64decode(part['body']['data']+'===').decode('utf-8','replace')
    return ''.join(_html(child) for child in part.get('parts',[]))

def receipt_text(plain, html):
    """Use visible HTML text when the receipt has no plain-text alternative."""
    if plain.strip():
        return plain
    html = re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', '', html, flags=re.I | re.S)
    html = re.sub(r'<(?:br\b[^>]*|/p\s*|/div\s*|/tr\s*)>', '\n', html, flags=re.I)
    return unescape(strip_tags(html))


def lookup_receipt(filename,since, *, sender=None):
    sender = (sender or settings.GMAIL_RECEIPT_SENDER).strip().lower()
    mailbox = GmailMailbox.current()
    address = mailbox.address if mailbox else settings.GMAIL_ADDRESS
    password = mailbox.app_password() if mailbox else settings.GMAIL_APP_PASSWORD
    if address and password:
        return _lookup_imap(filename, since, sender=sender)
    stamp=int(since.timestamp()); queries=[f'from:{sender} after:{stamp} "{filename}"',f'from:{sender} after:{stamp} {filename.split("-")[0]}']; seen=set()
    for query in queries:
        for item in _get('/messages',{'q':query,'maxResults':50}).get('messages',[]):
            if item['id'] in seen: continue
            seen.add(item['id']); raw=_get('/messages/'+item['id'],{'format':'full'}); payload=raw.get('payload',{}); headers={h['name'].lower():h['value'] for h in payload.get('headers',[])}; body=receipt_text(_text(payload), _html(payload)); match=re.findall(r'File\s*name\s*:\s*([A-Za-z0-9-]+\.xml)\b',body,re.I); when=datetime.fromtimestamp(int(raw.get('internalDate','0'))/1000,timezone.utc)
            if email.utils.parseaddr(headers.get('from',''))[1].lower() == sender and headers.get('subject','').strip()=='Tax Return Receipt Confirmation' and match==[filename] and when>=since:
                return {'found':True,'filename':filename,'message':{'id':raw['id'],'date':when.isoformat(),'from':headers.get('from',''),'to':headers.get('to',''),'subject':headers.get('subject',''),'text':body,'html':_html(payload)}}
    return {'found':False}

def test_imap_connection():
    mailbox=GmailMailbox.current(); address=mailbox.address if mailbox else settings.GMAIL_ADDRESS; password=mailbox.app_password() if mailbox else settings.GMAIL_APP_PASSWORD
    mailbox=imaplib.IMAP4_SSL('imap.gmail.com', 993)
    try:
        mailbox.login(address, password)
        return True
    finally:
        try: mailbox.logout()
        except Exception: pass

def _lookup_imap(filename, since, *, sender=None):
    """Search Gmail over IMAP; app-password mode needs no OAuth redirect URI."""
    sender = (sender or settings.GMAIL_RECEIPT_SENDER).strip().lower()
    config=GmailMailbox.current(); address=config.address if config else settings.GMAIL_ADDRESS; password=config.app_password() if config else settings.GMAIL_APP_PASSWORD
    mailbox=imaplib.IMAP4_SSL('imap.gmail.com', 993)
    try:
        mailbox.login(address, password)
        # Simulated receipts are commonly classified as Spam; search both
        # read-only folders without changing labels or marking mail read.
        for folder in ('INBOX', '"[Gmail]/Spam"'):
            try:
                mailbox.select(folder, readonly=True)
            except imaplib.IMAP4.error:
                continue
            status, data=mailbox.search(None, 'FROM', sender, 'SINCE', since.strftime('%d-%b-%Y'))
            if status != 'OK':
                continue
            for number in reversed(data[0].split()):
                status, parts=mailbox.fetch(number, '(BODY.PEEK[] INTERNALDATE)')
                if status != 'OK': continue
                raw=b''.join(part[1] for part in parts if isinstance(part, tuple))
                message=email.message_from_bytes(raw)
                received=email.utils.parsedate_to_datetime(message.get('Date',''))
                if received.tzinfo is None: received=received.replace(tzinfo=timezone.utc)
                body='\n'.join((part.get_payload(decode=True) or b'').decode('utf-8','replace') for part in message.walk() if part.get_content_type()=='text/plain')
                html='\n'.join((part.get_payload(decode=True) or b'').decode('utf-8','replace') for part in message.walk() if part.get_content_type()=='text/html')
                body=receipt_text(body, html)
                match=re.findall(r'File\s*name\s*:\s*([A-Za-z0-9-]+\.xml)\b',body,re.I)
                if email.utils.parseaddr(message.get('From',''))[1].lower() == sender and message.get('Subject','').strip()=='Tax Return Receipt Confirmation' and match==[filename] and received >= since:
                    return {'found':True,'filename':filename,'message':{'id':message.get('Message-ID', number.decode()),'date':received.isoformat(),'from':message.get('From',''),'to':message.get('To',''),'subject':message.get('Subject',''),'text':body,'html':html}}
        return {'found':False}
    finally:
        try: mailbox.logout()
        except Exception: pass
