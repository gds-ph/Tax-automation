"""Open read-only pages of the live dashboard over the network, signed in as the bot's own view-only account.

Used by the Claude Code CLI backend (feishu_doc_mcp), which has no access to the live database: the bot sees
exactly what its FEISHU_BOT_DASHBOARD_USERNAME account can see, never more.
"""
import atexit
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

from django.conf import settings

UUID = r'[0-9a-fA-F-]{36}'
# Read-only pages only: nothing here changes data, downloads files or opens admin/settings.
ALLOWED_PATHS = [re.compile(p) for p in (
    r'/', r'/clients/', rf'/clients/{UUID}/', r'/clients/directory/', r'/filings/', r'/filings/[a-z0-9-]{1,60}/',
    r'/work-orders/', rf'/work-orders/{UUID}/', r'/my-tasks/', r'/overview/')]
SAFE_QUERY = re.compile(r'''[^<>"'`\\#]{0,300}''')
MAX_LINKS = 80


class LiveDashboardError(Exception):
    pass


def configured():
    return bool(settings.FEISHU_BOT_DASHBOARD_USERNAME and settings.FEISHU_BOT_DASHBOARD_PASSWORD
                and settings.FEISHU_BOT_SITE_URL.startswith('https://'))


def allowed(path):
    parts = urlsplit(path)
    if parts.scheme or parts.netloc or not SAFE_QUERY.fullmatch(parts.query):
        return False
    return any(p.fullmatch(parts.path) for p in ALLOWED_PATHS)


class _Browser:
    """One signed-in browser per tool-server process (one Feishu message)."""

    def __init__(self):
        self.pw = self.browser = self.page = None

    def open(self):
        if self.page:
            return self.page
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        # The LAN proxy uses a locally issued certificate; the address itself is fixed by settings.
        context = self.browser.new_context(viewport={'width': 1440, 'height': 900}, ignore_https_errors=True)
        page = context.new_page()
        site = settings.FEISHU_BOT_SITE_URL
        page.goto(site + '/login/', wait_until='domcontentloaded', timeout=30000)
        # When Feishu sign-in is enabled the password form sits in a collapsed "Sign in with an account" section.
        page.evaluate("document.querySelectorAll('details.login-alt').forEach(d => d.open = true)")
        page.fill('#id_username', settings.FEISHU_BOT_DASHBOARD_USERNAME)
        page.fill('#id_password', settings.FEISHU_BOT_DASHBOARD_PASSWORD)
        with page.expect_navigation(timeout=30000):
            page.click('form.login-form [type=submit]')
        if urlsplit(page.url).path.startswith('/login'):
            raise LiveDashboardError('The assistant could not sign in to the dashboard.')
        self.page = page
        return page

    def close(self):
        try:
            if self.browser:
                self.browser.close()
            if self.pw:
                self.pw.stop()
        except Exception:
            pass

    def reset(self):
        """Close everything so the next call signs in again (e.g. after the session expired)."""
        self.close()
        self.pw = self.browser = self.page = None


_browser = _Browser()
atexit.register(_browser.close)


MAX_HIGHLIGHTS = 3
# Numbered red boxes drawn over the page (in document coordinates) just for the screenshot.
_DRAW_BOX = """([x, y, w, h, n]) => {
  const box = document.createElement('div');
  box.className = 'ner-highlight';
  Object.assign(box.style, {position: 'absolute', left: (x + scrollX - 5) + 'px', top: (y + scrollY - 5) + 'px',
    width: (w + 10) + 'px', height: (h + 10) + 'px', border: '3px solid #e11d2a', borderRadius: '8px',
    boxSizing: 'border-box', zIndex: 2147483647, pointerEvents: 'none'});
  if (n) {
    const tag = document.createElement('span');
    tag.textContent = n;
    Object.assign(tag.style, {position: 'absolute', left: '-14px', top: '-14px', width: '24px', height: '24px',
      borderRadius: '50%', background: '#e11d2a', color: '#fff', font: '700 13px/24px system-ui, sans-serif',
      textAlign: 'center'});
    box.appendChild(tag);
  }
  document.body.appendChild(box);
}"""


def _visible(locator, limit=10):
    for i in range(min(locator.count(), limit)):
        element = locator.nth(i)
        if element.is_visible():
            yield element


def _find(page, text):
    """A visible link, button or tab labelled text (the whole menu item or tab), or, when the label is only
    part of a larger clickable element such as a client card, the smallest element showing that text."""
    wanted = ' '.join(text.split()).lower()
    for role in ('link', 'button', 'tab'):
        for element in _visible(page.get_by_role(role, name=text)):
            own = ' '.join(element.inner_text().split()).lower()
            if len(own) <= len(wanted) + 3:  # allows trailing arrows and counters
                return element
    best, best_area = None, None
    for element in _visible(page.get_by_text(text)):
        box = element.bounding_box()
        if box and (best_area is None or box['width'] * box['height'] < best_area):
            best, best_area = element, box['width'] * box['height']
    return best


def _highlight(page, labels):
    """Draws numbered boxes (no number for a single box); returns the labels that were not found."""
    missing, found = [], []
    for label in labels:
        element = _find(page, label)
        (found if element else missing).append(element or label)
    if found:
        found[0].scroll_into_view_if_needed(timeout=5000)
    for n, element in enumerate(found, 1):
        box = element.bounding_box()
        if box:
            page.evaluate(_DRAW_BOX, [box['x'], box['y'], box['width'], box['height'],
                                      str(n) if len(found) > 1 else ''])
    return missing


def _open(path):
    """Loads an allowed path in the signed-in browser and returns the page."""
    from playwright.sync_api import Error as PlaywrightError
    page = _browser.open()
    response = page.goto(settings.FEISHU_BOT_SITE_URL + path, wait_until='load', timeout=30000)
    try:
        # Pages that poll for notifications never go fully idle; give the rest a moment, then capture.
        page.wait_for_load_state('networkidle', timeout=5000)
    except PlaywrightError:
        pass
    if urlsplit(page.url).path.startswith('/login'):
        _browser.reset()
        raise LiveDashboardError('The assistant was signed out of the dashboard.')
    if response is None or response.status >= 400:
        raise LiveDashboardError('That page could not be opened with the assistant\'s permissions.')
    return page


APPROVAL_LIST = '/work-orders/?status=AWAITING_SUBMISSION_APPROVAL'
_ROWS = """() => [...document.querySelectorAll('table tbody tr')].map(tr => {
  const link = tr.querySelector('a.client-link'), cells = tr.querySelectorAll('td');
  if (!link || cells.length < 6) return null;
  const text = el => (el ? el.innerText : '').trim();
  return {path: link.getAttribute('href'), client: text(link), reference: text(cells[0].querySelector('.row-sub')),
          period: text(cells[1].querySelector('strong')), form: text(cells[1].querySelector('.row-sub')),
          status: text(cells[2]), created_by: text(cells[3]),
          needs_review: /Review for approval/.test(text(cells[5]))};
}).filter(Boolean)"""


_WORKERS = """() => [...document.querySelectorAll('li.worker-row')].map(li => {
  const text = el => (el ? el.innerText : '').replace(/\\s+/g, ' ').trim();
  return {name: text(li.querySelector('strong')), online: !!li.querySelector('.worker-dot.online'),
          connection: text(li.querySelector('.pill')), activity: text(li.querySelector('.row-sub')),
          heartbeat: text(li.querySelector('.worker-seen'))};
})"""

# Playwright runs an event loop on the thread that uses it, and Django refuses database calls there, so
# background checks drive the browser from this one thread and keep their database work on their own.
_browser_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dashboard-browser')


def in_browser_thread(function, *args):
    return _browser_thread.submit(function, *args).result(timeout=300)


def worker_statuses():
    """The Workers panel of the live dashboard: dicts with name, online, connection, activity and heartbeat."""
    if not configured():
        raise LiveDashboardError('Live dashboard access is not configured.')
    from playwright.sync_api import Error as PlaywrightError
    try:
        return [row for row in _open('/work-orders/').evaluate(_WORKERS) if row['name']]
    except PlaywrightError:
        _browser.reset()
        raise LiveDashboardError('The browser could not load the workers panel.') from None


def awaiting_approvals(max_pages=10):
    """Work orders on the live dashboard that still show "Review for approval", as dicts with path, client,
    reference, period, form and created_by."""
    if not configured():
        raise LiveDashboardError('Live dashboard access is not configured.')
    from playwright.sync_api import Error as PlaywrightError
    rows = []
    try:
        for number in range(1, max_pages + 1):
            page = _open(f'{APPROVAL_LIST}&page={number}')
            rows += [row for row in page.evaluate(_ROWS) if row['needs_review'] and allowed(row['path'])]
            if not page.locator('nav.pagination a', has_text='Next').count():
                break
    except PlaywrightError:
        _browser.reset()
        raise LiveDashboardError('The browser could not load the work-order list.') from None
    return rows


def completed_packages(max_pages=10):
    """Work orders in the live dashboard's "Completed this month" list (final package generated), as dicts like
    awaiting_approvals() plus status ("Receipt package generated" or "Simulation complete - package generated")."""
    if not configured():
        raise LiveDashboardError('Live dashboard access is not configured.')
    from playwright.sync_api import Error as PlaywrightError
    rows = []
    try:
        for number in range(1, max_pages + 1):
            page = _open(f'/work-orders/?kpi=completed&page={number}')
            rows += [row for row in page.evaluate(_ROWS) if allowed(row['path'])]
            if not page.locator('nav.pagination a', has_text='Next').count():
                break
    except PlaywrightError:
        _browser.reset()
        raise LiveDashboardError('The browser could not load the completed work orders.') from None
    return rows


def view(path, highlight=()):
    """Returns (png bytes, page title, [(link text, path)], [labels not found]) for an allowed dashboard path.
    highlight: up to three on-screen labels (link, button or tab text) to draw a red box around."""
    labels = [' '.join(str(h).split())[:80] for h in highlight if str(h).strip()][:MAX_HIGHLIGHTS]
    if not configured():
        raise LiveDashboardError('Live dashboard access is not configured.')
    if not allowed(path):
        raise LiveDashboardError('That page is not available to the assistant.')
    from playwright.sync_api import Error as PlaywrightError
    try:
        page = _open(path)
        missing = _highlight(page, labels) if labels else []
        png = page.screenshot(full_page=False, type='png')
        page.evaluate("document.querySelectorAll('.ner-highlight').forEach(e => e.remove())")
        title = page.title()
        raw = page.eval_on_selector_all('a[href]', 'els => els.map(a => [a.innerText.trim(), a.getAttribute("href")])')
    except PlaywrightError:
        raise LiveDashboardError('The browser could not load the page.') from None
    links, seen = [], set()
    base = urlsplit(page.url)
    for text, href in raw:
        text = ' '.join(text.split())[:80]
        target = urlsplit(urljoin(page.url, href or ''))
        if target.netloc != base.netloc:
            continue
        href = target.path + (f'?{target.query}' if target.query else '')
        if text and allowed(href) and (text, href) not in seen:
            seen.add((text, href))
            links.append((text, href))
    return png, title, links[:MAX_LINKS], missing
