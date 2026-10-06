"""Minimal stdio MCP server exposing read_doc, record_feedback and (private chats only) view_dashboard_page to
the Claude Code CLI backend (see feishu_bot.claude_cli). The sender comes from EBIR_BOT_SENDER, set by the bot,
not by the model."""
import base64
import json
import os
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from feishu_bot import tools

SERVED = ('read_doc', 'record_feedback')
MAX_SCREENSHOTS = 3

VIEW_PAGE = {
    'name': 'view_dashboard_page',
    'description': "Open a page of the live eBIR dashboard (signed in as the assistant's view-only account) and "
                   'see a screenshot of it, plus the links on the page so you can open the next page. The '
                   'screenshot is also sent to the person after your reply. Start from "/clients/", "/work-orders/", '
                   '"/my-tasks/" or "/overview/"; to reach a specific client or work order, open a list and follow '
                   'its link. Search clients with "/clients/?tab=all&q=<name or code>&form=<form number>". Use it '
                   'to show where something is, or to answer what the dashboard currently shows. When showing '
                   'where to click, pass highlight with the exact on-screen label(s) to draw a red box around '
                   '(several are numbered in order); open the page once first if you do not know the labels.',
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['path'], 'properties': {
        'path': {'type': 'string', 'description': "A dashboard path from the start pages or from a previous "
                                                  "result's links, e.g. \"/clients/\"."},
        'highlight': {'type': 'array', 'maxItems': 3, 'items': {'type': 'string'},
                      'description': 'Up to three visible labels (link, button or tab text) to box in red, in '
                                     'click order, e.g. ["History"].'}}},
}


def _tool_list(ctx):
    listed = [{'name': t['name'], 'description': t['description'], 'inputSchema': t['input_schema']}
              for t in tools.TOOLS if t['name'] in SERVED]
    return listed + ([VIEW_PAGE] if getattr(ctx, 'screenshot_dir', '') else [])


def sender_context():
    try:
        sender = json.loads(os.environ.get('EBIR_BOT_SENDER') or '{}')
    except ValueError:
        sender = {}
    user = get_user_model().objects.filter(pk=sender.get('user_id'), is_active=True).first() if sender.get('user_id') else None
    ctx = tools.ToolContext(user=user, sender_open_id=sender.get('open_id') or '', sender_name=sender.get('name') or '',
                            chat_id=sender.get('chat_id') or '', message_id=sender.get('message_id') or '')
    ctx.screenshot_dir = sender.get('screenshot_dir') or ''
    return ctx


def _text(text, error=False):
    return {'content': [{'type': 'text', 'text': text}], **({'isError': True} if error else {})}


def _view_page(args, ctx):
    from feishu_bot import live_dashboard
    if not getattr(ctx, 'screenshot_dir', ''):
        return _text('Dashboard pages are only shown in a private chat with the assistant.', error=True)
    folder = Path(ctx.screenshot_dir)
    taken = len(list(folder.glob('*.png')))
    if taken >= MAX_SCREENSHOTS:
        return _text(f'At most {MAX_SCREENSHOTS} pages per message.', error=True)
    highlight = args.get('highlight') or []
    if not isinstance(highlight, list):
        highlight = [highlight]
    try:
        png, title, links, missing = live_dashboard.view(str(args.get('path') or ''), highlight)
    except live_dashboard.LiveDashboardError as exc:
        return _text(str(exc), error=True)
    (folder / f'{taken + 1:02d}.png').write_bytes(png)
    listing = '\n'.join(f'- {text} -> {href}' for text, href in links) or '(none)'
    note = (f'\nNot found on screen, so not boxed: {", ".join(missing)}. Check the exact label in the screenshot.'
            if missing else '')
    return {'content': [
        {'type': 'image', 'data': base64.standard_b64encode(png).decode(), 'mimeType': 'image/png'},
        {'type': 'text', 'text': f'Page: {title}\nThis screenshot will be sent in the chat after your reply.{note}\n'
                                 f'Links on this page (text -> path):\n{listing}'}]}


def _call(params, ctx):
    name, args = params.get('name'), params.get('arguments') or {}
    if name == VIEW_PAGE['name']:
        return _view_page(args, ctx)
    if name not in SERVED:
        return _text('Unknown tool.', error=True)
    if name == 'record_feedback' and not ctx.message_id:
        return _text('Feedback can only be recorded from a Feishu message.', error=True)
    try:
        return _text(tools.run(name, args, ctx))
    except tools.ToolError as exc:
        return _text(str(exc), error=True)


class Command(BaseCommand):
    help = "Serve the assistant's tools to the Claude Code CLI over MCP (stdio)."

    def handle(self, *args, **options):
        ctx = sender_context()
        out = sys.stdout.buffer
        for raw in sys.stdin.buffer:
            try:
                request = json.loads(raw.decode('utf-8'))
            except ValueError:
                continue
            if 'id' not in request:
                continue  # notification
            method, params = request.get('method'), request.get('params') or {}
            reply = {'jsonrpc': '2.0', 'id': request['id']}
            if method == 'initialize':
                reply['result'] = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                                   'capabilities': {'tools': {}}, 'serverInfo': {'name': 'ebir', 'version': '1'}}
            elif method == 'tools/list':
                reply['result'] = {'tools': _tool_list(ctx)}
            elif method == 'tools/call':
                reply['result'] = _call(params, ctx)
            elif method == 'ping':
                reply['result'] = {}
            else:
                reply['error'] = {'code': -32601, 'message': 'Method not found'}
            out.write(json.dumps(reply, ensure_ascii=False).encode('utf-8') + b'\n')
            out.flush()
