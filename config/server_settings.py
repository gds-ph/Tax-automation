"""Linux deployment behind the private Compose reverse proxy."""
import os
from pathlib import Path

# Base settings keep the workstation loopback-only. Apply LAN hosts here only.
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1'
os.environ['DJANGO_DEBUG'] = 'False'
from .settings import *  # noqa: E402,F403

ALLOWED_HOSTS = [x.strip() for x in os.environ.get('SERVER_ALLOWED_HOSTS', '').split(',') if x.strip()]
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Set explicit SERVER_ALLOWED_HOSTS for the Linux server.')
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.environ.get('SERVER_CSRF_ORIGINS', '').split(',') if x.strip()]
DATABASES['default']['NAME'] = Path('/data/db.sqlite3')
DATABASES['default']['OPTIONS'] = {'timeout': 30}
MEDIA_ROOT = Path('/data/media')
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
CLIENT_FILES_URL = 'http://client-files:3020'
CLIENT_FILES_ALLOWED_HOSTS = {'client-files'}
COR_NODE_MODULES = '/app/deploy/docker/node_modules'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Web is reachable only through Caddy, which overwrites forwarded headers.
# Submission stays disabled until the Windows worker cutover is verified.
# Live 1601C submission is an explicit server-side switch. Keep it disabled by
# default; production can enable it only after the PAD Stage 2 worker is ready.
ENABLE_1601C_SUBMISSION = os.environ.get('ENABLE_1601C_SUBMISSION', '0') == '1'
