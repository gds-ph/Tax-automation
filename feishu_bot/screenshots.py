"""Render a dashboard page as the requesting user with a two-minute session that is deleted afterwards."""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore


class ScreenshotError(Exception):
    pass


def capture(user, path, *, width=1440, height=900):
    if not path.startswith('/') or path.startswith('//'):
        raise ScreenshotError('Only dashboard paths can be captured.')
    site = settings.FEISHU_BOT_SITE_URL
    host = urlsplit(site)
    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.set_expiry(120)
    session.create()
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    # The LAN proxy uses a locally issued certificate; the address itself is fixed by settings.
                    context = browser.new_context(viewport={'width': width, 'height': height},
                                                  ignore_https_errors=True, device_scale_factor=1)
                    context.add_cookies([{
                        'name': settings.SESSION_COOKIE_NAME, 'value': session.session_key,
                        'domain': host.hostname, 'path': '/', 'httpOnly': True,
                        'secure': host.scheme == 'https', 'sameSite': 'Lax'}])
                    page = context.new_page()
                    response = page.goto(site + path, wait_until='networkidle', timeout=30000)
                    if response is None or response.status >= 400 or '/login' in urlsplit(page.url).path:
                        raise ScreenshotError('The page could not be opened with your permissions.')
                    return page.screenshot(full_page=False, type='png')
                finally:
                    browser.close()
        except PlaywrightError:
            raise ScreenshotError('The browser could not load the page.') from None
    finally:
        session.delete()
