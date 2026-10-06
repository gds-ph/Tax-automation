"""Isolated local Docker trial. Never imports the workstation database or secrets."""
import os
from pathlib import Path
import secrets

_data = Path('/data')
_key_file = _data / 'django-secret-key'
try:
    with open(_key_file, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        stream.write(secrets.token_urlsafe(64))
except FileExistsError:
    pass
os.environ['DJANGO_SECRET_KEY'] = _key_file.read_text().strip()
os.environ['DJANGO_DEBUG'] = 'False'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1'

from .settings import *  # noqa: E402,F403

DATABASES['default']['NAME'] = _data / 'db.sqlite3'
DATABASES['default']['OPTIONS'] = {'timeout': 30}
MEDIA_ROOT = _data / 'media'
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
ENABLE_1601C_SUBMISSION = False
CLIENT_FILES_ALLOWED_HOSTS = {'host.docker.internal', 'localhost', '127.0.0.1'}
