"""Tools the assistant may call. Every data tool enforces the linked user's own Django permissions."""
import base64
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Concat
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

log = logging.getLogger(__name__)

DOCS_DIR = Path(settings.BASE_DIR) / 'docs'
# Deployment and credential procedures are for administrators, not the chat assistant.
HIDDEN_DOCS = {'docker-local', 'docker-server', 'worker-https', 'worker-api-setup', 'feishu-login'}
MAX_DOC_CHARS = 40000


@dataclass
class ToolContext:
    user: object = None            # linked Django user, or None
    data_allowed: bool = False     # False for unlinked senders and (by default) group chats
    reason: str = ''               # shown to the model when data is not allowed
    sender_open_id: str = ''
    sender_name: str = ''
    chat_id: str = ''
    message_id: str = ''
    images: list = field(default_factory=list)     # screenshots to send after the reply
    feedback: list = field(default_factory=list)


def doc_index():
    docs = []
    for path in sorted(DOCS_DIR.glob('*.md')):
        if path.stem in HIDDEN_DOCS:
            continue
        title = path.read_text(encoding='utf-8').split('\n', 1)[0].lstrip('# ').strip()
        docs.append((path.stem, title))
    return docs


TOOLS = [
    {
        'name': 'read_doc',
        'description': 'Read one page of the eBIR dashboard documentation by name (see the index in the '
                       'system prompt). Use it before answering how-to or "why does it do this" questions.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['name'],
                         'properties': {'name': {'type': 'string', 'description': 'Doc name, e.g. "cor-reader", or "README".'}}},
    },
    {
        'name': 'find_clients',
        'description': 'Search clients by registered name, trade name, client code or TIN digits. Returns at most 10.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['query'],
                         'properties': {'query': {'type': 'string'}}},
    },
    {
        'name': 'find_work_orders',
        'description': 'List work orders (tax filings), newest first, optionally filtered by client name/TIN/work order '
                       'number text, status code, or only those assigned to the person asking. Returns at most 15.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'properties': {
            'query': {'type': 'string', 'description': 'Client name, TIN digits or work order number.'},
            'status': {'type': 'string', 'description': 'A status code such as AWAITING_SUBMISSION_APPROVAL.'},
            'mine': {'type': 'boolean', 'description': 'Only work orders assigned to the person asking.'}}},
    },
    {
        'name': 'get_work_order',
        'description': 'Full status of one work order: period, form, status, errors, approval and assignment.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['work_order'],
                         'properties': {'work_order': {'type': 'string', 'description': 'Work order number or id.'}}},
    },
    {
        'name': 'take_screenshot',
        'description': 'Capture a dashboard page as the person asking sees it, and send the image in the chat. '
                       'You also receive the image so you can describe it.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['page'], 'properties': {
            'page': {'type': 'string', 'enum': ['clients', 'client', 'work_orders', 'work_order', 'my_tasks', 'overview']},
            'id': {'type': 'string', 'description': 'Client id for "client"; work order number or id for "work_order".'}}},
    },
    {
        'name': 'record_feedback',
        'description': 'Save feedback, a bug report or a change request for the developer. Call it once the request '
                       'is clear (after at most a couple of clarifying questions), not for every message.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['category', 'summary', 'details'], 'properties': {
            'category': {'type': 'string', 'enum': ['bug', 'feature', 'change', 'data', 'question', 'other']},
            'summary': {'type': 'string', 'description': 'One line, under 120 characters.'},
            'details': {'type': 'string', 'description': 'Everything the developer needs: what, where, expected '
                                                         'behaviour, the requester\'s answers to your questions.'}}},
    },
]

DATA_TOOLS = {'find_clients', 'find_work_orders', 'get_work_order', 'take_screenshot'}


class ToolError(Exception):
    pass


class Blocks(list):
    """Tool output that is already API content blocks (e.g. an image), not data to serialise."""


def run(name, args, ctx):
    """Returns tool_result content (a string or content blocks). Raises ToolError for a reportable refusal."""
    if name in DATA_TOOLS and not ctx.data_allowed:
        raise ToolError(ctx.reason)
    handler = HANDLERS.get(name)
    if handler is None:
        raise ToolError('Unknown tool.')
    return handler(args, ctx)


def _need(ctx, perm):
    if not ctx.user.has_perm(perm):
        raise ToolError('Your dashboard account does not have permission to view this.')


def read_doc(args, ctx):
    name = str(args.get('name', '')).strip().removesuffix('.md')
    if name.upper() == 'README':
        path = Path(settings.BASE_DIR) / 'README.md'
    elif re.fullmatch(r'[a-z0-9-]{1,60}', name) and name not in HIDDEN_DOCS:
        path = DOCS_DIR / f'{name}.md'
    else:
        raise ToolError('No such document.')
    if not path.is_file():
        raise ToolError('No such document.')
    text = path.read_text(encoding='utf-8')
    return text[:MAX_DOC_CHARS] + ('\n[truncated]' if len(text) > MAX_DOC_CHARS else '')


def _tin(obj):
    return '-'.join(p for p in (obj.tin1, obj.tin2, obj.tin3, obj.tin4) if p)


def find_clients(args, ctx):
    from workorders.models import Client
    _need(ctx, 'workorders.view_client')
    query = str(args.get('query', '')).strip()[:100]
    digits = re.sub(r'\D', '', query)
    clients = Client.objects.annotate(tin=Concat('tin1', 'tin2', 'tin3', 'tin4'))
    match = Q(registered_name__icontains=query) | Q(trade_name__icontains=query) | Q(client_code__icontains=query)
    if len(digits) >= 3:
        match |= Q(tin__contains=digits)
    rows = clients.filter(match).order_by('registered_name')[:10]
    return [{'id': str(c.pk), 'client_code': c.client_code, 'name': c.registered_name, 'trade_name': c.trade_name,
             'tin': _tin(c), 'rdo': c.rdo_code, 'type': c.get_client_type_display(), 'active': c.is_active,
             'link': _link('workorders:client-detail', c.pk)} for c in rows] or 'No matching clients.'


def _work_order(ref, ctx):
    from workorders.models import WorkOrder
    ref = str(ref or '').strip()
    query = WorkOrder.objects.select_related('assigned_to', 'client')
    match = Q(work_order_id__iexact=ref)
    if re.fullmatch(r'[0-9a-fA-F-]{36}', ref):
        match |= Q(pk=ref)
    try:
        return query.get(match)
    except WorkOrder.DoesNotExist:
        raise ToolError('No work order with that number.') from None


def _period(wo):
    if wo.filing_quarter:
        return f'Q{wo.filing_quarter} {wo.filing_year}'
    if wo.filing_month:
        return f'{wo.filing_year}-{wo.filing_month:02d}'
    return wo.filing_year


def _summary(wo):
    return {'work_order': wo.work_order_id, 'id': str(wo.pk), 'client': wo.client_name or wo.registered_name,
            'tin': _tin(wo), 'form': wo.expected_form_number or wo.form_code, 'period': _period(wo),
            'status': wo.operational_status, 'status_code': wo.status,
            'assigned_to': (wo.assigned_to.get_full_name() or wo.assigned_to.username) if wo.assigned_to else None,
            'updated': timezone.localtime(wo.updated_at).strftime('%Y-%m-%d %H:%M'),
            'link': _link('workorders:detail', wo.pk)}


def find_work_orders(args, ctx):
    from workorders.models import WorkOrder
    _need(ctx, 'workorders.view_workorder')
    orders = WorkOrder.objects.select_related('assigned_to').filter(is_archived=False)
    query = str(args.get('query') or '').strip()[:100]
    if query:
        digits = re.sub(r'\D', '', query)
        match = (Q(client_name__icontains=query) | Q(registered_name__icontains=query)
                 | Q(work_order_id__icontains=query))
        if len(digits) >= 3:
            orders = orders.annotate(tin=Concat('tin1', 'tin2', 'tin3', 'tin4'))
            match |= Q(tin__contains=digits)
        orders = orders.filter(match)
    if args.get('status'):
        orders = orders.filter(status=str(args['status']).strip().upper())
    if args.get('mine'):
        orders = orders.filter(assigned_to=ctx.user)
    rows = [_summary(wo) for wo in orders.order_by('-updated_at')[:15]]
    return rows or 'No matching work orders.'


def get_work_order(args, ctx):
    _need(ctx, 'workorders.view_workorder')
    wo = _work_order(args.get('work_order'), ctx)
    result = _summary(wo)
    result.update({'zero_filing': wo.zero_filing, 'attempts': wo.attempt_count,
                   'approved_for_submission': wo.approved_for_submission,
                   'approved_by': wo.approved_by.username if wo.approved_by_id else None,
                   'error_code': wo.error_code or None, 'error_message': (wo.error_message or '')[:1000] or None,
                   'created': timezone.localtime(wo.created_at).strftime('%Y-%m-%d %H:%M')})
    return result


SCREENSHOT_PAGES = {
    'clients': ('workorders:clients', 'workorders.view_client'),
    'client': ('workorders:client-detail', 'workorders.view_client'),
    'work_orders': ('workorders:list', 'workorders.view_workorder'),
    'work_order': ('workorders:detail', 'workorders.view_workorder'),
    'my_tasks': ('workorders:my-tasks', 'workorders.view_workorder'),
    'overview': ('workorders:overview', 'workorders.view_workorder'),
}


def take_screenshot(args, ctx):
    from .screenshots import ScreenshotError, capture
    page = args.get('page')
    if page not in SCREENSHOT_PAGES:
        raise ToolError('Unknown page.')
    route, perm = SCREENSHOT_PAGES[page]
    _need(ctx, perm)
    if len(ctx.images) >= 3:
        raise ToolError('At most three screenshots per message.')
    if page == 'work_order':
        target = [_work_order(args.get('id'), ctx).pk]
    elif page == 'client':
        from workorders.models import Client
        client = Client.objects.filter(pk=args.get('id')).first() if re.fullmatch(r'[0-9a-fA-F-]{36}', str(args.get('id') or '')) else None
        if client is None:
            raise ToolError('Find the client first with find_clients and pass its id.')
        target = [client.pk]
    else:
        target = []
    try:
        png = capture(ctx.user, reverse(route, args=target))
    except (ScreenshotError, NoReverseMatch) as exc:
        raise ToolError(str(exc) or 'The page could not be captured.') from None
    ctx.images.append(png)
    return Blocks([{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                         'data': base64.standard_b64encode(png).decode()}},
            {'type': 'text', 'text': 'Screenshot captured; it will be sent in the chat after your reply.'}])


def record_feedback(args, ctx):
    from .models import Feedback
    category = args.get('category')
    if category not in Feedback.Category.values:
        category = Feedback.Category.OTHER
    summary = str(args.get('summary') or '').strip()[:200]
    details = str(args.get('details') or '').strip()[:8000]
    if not summary or not details:
        raise ToolError('A summary and details are required.')
    feedback = Feedback.objects.create(
        category=category, summary=summary, details=details, reporter=ctx.user,
        reporter_open_id=ctx.sender_open_id, reporter_name=ctx.sender_name[:150],
        chat_id=ctx.chat_id, source_message_id=ctx.message_id)
    ctx.feedback.append(feedback)
    return f'Saved as {feedback.reference}. {settings.FEISHU_BOT_DEVELOPER_NAME} will be notified.'


def _link(route, pk):
    try:
        return settings.FEISHU_BOT_SITE_URL + reverse(route, args=[pk])
    except NoReverseMatch:
        return None


HANDLERS = {'read_doc': read_doc, 'find_clients': find_clients, 'find_work_orders': find_work_orders,
            'get_work_order': get_work_order, 'take_screenshot': take_screenshot,
            'record_feedback': record_feedback}
