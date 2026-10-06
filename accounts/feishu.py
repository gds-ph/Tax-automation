"""Feishu OAuth login. No email-based account linking or token persistence."""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Permission
from django.db import transaction, IntegrityError
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST, require_GET

from .models import FeishuIdentity


class LoginFailed(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def configured():
    uri = urlsplit(settings.FEISHU_REDIRECT_URI)
    return bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET and settings.FEISHU_TENANT_KEY
                and uri.scheme == 'https' and uri.hostname and not uri.username
                and not uri.password and not uri.query and not uri.fragment)


@sensitive_variables()
def api(path, *, payload=None, token=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    request = Request('https://open.feishu.cn/open-apis/' + path, data=data, headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(100001)
        if len(raw) > 100000:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('code', 0) != 0 or result.get('error'):
            raise ValueError()
        return result
    except (OSError, ValueError, TypeError):
        raise LoginFailed() from None


def failure(request):
    from audit.operational import record
    record('feishu_login_failed', level='WARNING')
    messages.error(request, 'Feishu sign-in could not be completed. Retry or contact your administrator.')
    return redirect('login')


@never_cache
@require_POST
def start(request):
    if not configured():
        return failure(request)
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    request.session['feishu_login'] = {'state': state, 'verifier': verifier, 'created': time.time()}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return redirect('https://accounts.feishu.cn/open-apis/authen/v1/authorize?' + urlencode({
        'client_id': settings.FEISHU_APP_ID, 'redirect_uri': settings.FEISHU_REDIRECT_URI,
        'response_type': 'code', 'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256',
    }))


@sensitive_variables()
def authenticate_identity(info):
    tenant = info.get('tenant_key')
    subject = info.get('open_id')
    if (tenant != settings.FEISHU_TENANT_KEY or not isinstance(subject, str)
            or not subject or len(subject) > 150):
        raise LoginFailed()
    identity = {'app_id': settings.FEISHU_APP_ID, 'tenant_key': tenant, 'open_id': subject}
    with transaction.atomic():
        existing = FeishuIdentity.objects.select_related('user').filter(**identity).first()
        if existing:
            user = existing.user
        else:
            # A random username cannot accidentally link to an existing local administrator.
            user = get_user_model()(username='feishu_' + secrets.token_hex(16),
                                    first_name=str(info.get('name') or '')[:150])
            user.set_unusable_password()
            user.save()
            FeishuIdentity.objects.create(user=user, **identity)
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='workorders', codename__in=[
                'view_client', 'view_workorder', 'view_clientfilingprofile',
                'view_formdefinition', 'view_workordersnapshot', 'view_prepared_pdf',
                'add_workorder', 'change_workorder', 'add_client', 'change_client',
                'add_clientfilingprofile']))
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='automation_api', codename='approve_stage2'))
        if not user.is_active:
            raise LoginFailed()
    return user


@never_cache
@require_GET
@sensitive_variables()
def callback(request):
    pending = request.session.pop('feishu_login', None)
    state = request.GET.get('state', '')
    if (not configured() or not pending or not state
            or not secrets.compare_digest(state, pending['state'])
            or not 0 <= time.time() - pending['created'] <= 600
            or request.GET.get('error') or not request.GET.get('code')):
        return failure(request)
    try:
        tokens = api('authen/v2/oauth/token', payload={
            'grant_type': 'authorization_code', 'client_id': settings.FEISHU_APP_ID,
            'client_secret': settings.FEISHU_APP_SECRET, 'code': request.GET['code'],
            'redirect_uri': settings.FEISHU_REDIRECT_URI, 'code_verifier': pending['verifier'],
        })
        access_token = tokens.get('access_token')
        if not isinstance(access_token, str) or not access_token:
            raise LoginFailed()
        info = api('authen/v1/user_info', token=access_token).get('data')
        if not isinstance(info, dict):
            raise LoginFailed()
        user = authenticate_identity(info)
    except (LoginFailed, IntegrityError):
        return failure(request)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    response = redirect(settings.LOGIN_REDIRECT_URL)
    response['Referrer-Policy'] = 'no-referrer'
    return response
