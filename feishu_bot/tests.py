import json
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings

from accounts.models import FeishuIdentity
from . import agent, feishu_api, handler, tools
from .models import BotMessage, Feedback


def event(text='@_user_1 hello', chat_type='group', message_id='om_1', open_id='ou_staff',
          mentions=('ou_bot',), parent_id=None, root_id=None, tenant='office'):
    return NS(event=NS(
        sender=NS(sender_type='user', tenant_key=tenant, sender_id=NS(open_id=open_id)),
        message=NS(message_id=message_id, root_id=root_id, parent_id=parent_id, chat_id='oc_chat',
                   chat_type=chat_type, message_type='text', content=json.dumps({'text': text}),
                   mentions=[NS(key=f'@_user_{i + 1}', name='BMS', id=NS(open_id=m)) for i, m in enumerate(mentions)])))


@override_settings(FEISHU_BOT_APP_ID='cli_test', FEISHU_BOT_TENANT_KEY='office', FEISHU_BOT_GROUP_DATA=False,
                   FEISHU_BOT_FEEDBACK_CHAT_ID='oc_dev', FEISHU_BOT_HOURLY_LIMIT=40)
@patch('feishu_bot.feishu_api.update_markdown')
@patch('feishu_bot.feishu_api.user_name', return_value='Dhee')
@patch('feishu_bot.feishu_api.bot_open_id', return_value='ou_bot')
@patch('feishu_bot.feishu_api.reply_markdown', side_effect=lambda message_id, text: 'om_reply_' + message_id)
@patch('feishu_bot.agent.respond', return_value='Noted.')
class HandlerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='staff', first_name='Dhee')
        FeishuIdentity.objects.create(user=self.user, app_id='cli_test', tenant_key='office', open_id='ou_staff')

    def test_group_message_without_bot_mention_is_ignored(self, respond, reply, *_):
        handler.handle(event(mentions=('ou_someone_else',)))
        respond.assert_not_called()
        self.assertFalse(BotMessage.objects.exists())

    def test_other_tenant_ignored(self, respond, reply, *_):
        handler.handle(event(tenant='outsider'))
        respond.assert_not_called()

    def test_redelivered_event_answered_once(self, respond, reply, *_):
        handler.handle(event())
        handler.handle(event())
        self.assertEqual(respond.call_count, 1)
        reply.assert_called_once_with('om_1', handler.THINKING)
        self.assertEqual(list(BotMessage.objects.values_list('role', flat=True)), ['user', 'assistant'])

    def test_placeholder_replaced_by_answer(self, respond, reply, name, bot, update):
        handler.handle(event())
        update.assert_called_once_with('om_reply_om_1', 'Noted.')
        self.assertTrue(BotMessage.objects.filter(role='assistant', message_id='om_reply_om_1').exists())

    def test_answer_sent_as_new_reply_if_placeholder_cannot_be_updated(self, respond, reply, name, bot, update):
        update.side_effect = feishu_api.FeishuError('update')
        handler.handle(event())
        self.assertEqual([c.args for c in reply.call_args_list], [('om_1', handler.THINKING), ('om_1', 'Noted.')])

    @patch('feishu_bot.feishu_api.get_message', return_value=('user', 'text', {'text': 'Sort Saved by date, please'}))
    def test_bare_mention_reply_answers_quoted_message(self, get_message, respond, *_):
        handler.handle(event(text='@_user_1', parent_id='om_christian'))
        blocks = respond.call_args.args[1]
        self.assertIn('Sort Saved by date, please', blocks[0]['text'])
        self.assertEqual(blocks[-1]['text'], 'Dhee: (Please answer the quoted message.)')

    def test_bare_mention_without_reply_is_ignored(self, respond, *_):
        handler.handle(event(text='@_user_1'))
        respond.assert_not_called()

    def test_bot_mention_removed_and_group_data_blocked(self, respond, *_):
        handler.handle(event())
        history, blocks, ctx, chat_type = respond.call_args.args
        self.assertEqual(blocks[-1]['text'], 'Dhee: hello')
        self.assertEqual(ctx.user, self.user)
        self.assertFalse(ctx.data_allowed)
        self.assertIn('group chat', ctx.reason)

    def test_private_chat_allows_linked_user_data(self, respond, *_):
        handler.handle(event(chat_type='p2p', mentions=()))
        ctx = respond.call_args.args[2]
        self.assertTrue(ctx.data_allowed)

    def test_unlinked_sender_gets_no_data(self, respond, *_):
        handler.handle(event(chat_type='p2p', mentions=(), open_id='ou_stranger'))
        ctx = respond.call_args.args[2]
        self.assertIsNone(ctx.user)
        self.assertFalse(ctx.data_allowed)
        self.assertEqual(ctx.sender_name, 'Dhee')

    def test_thread_history_alternates_and_ends_with_assistant(self, respond, *_):
        handler.handle(event(message_id='om_1'))
        handler.handle(event(message_id='om_2', root_id='om_1', parent_id='om_reply_om_1', text='@_user_1 yes'))
        history = respond.call_args.args[0]
        self.assertEqual([h['role'] for h in history], ['user', 'assistant'])
        self.assertEqual(history[0]['content'], 'Dhee: hello')

    @patch('feishu_bot.feishu_api.send_markdown')
    def test_feedback_forwarded_to_developer_chat(self, send, respond, *_):
        def fake(history, blocks, ctx, chat_type):
            tools.run('record_feedback', {'category': 'feature', 'summary': 'Daily BSP rate',
                                          'details': 'Finance enters the rate.'}, ctx)
            return 'Saved.'
        respond.side_effect = fake
        handler.handle(event())
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.reporter, self.user)
        self.assertEqual(feedback.reporter_name, 'Dhee')
        self.assertEqual(send.call_args.args[0], 'oc_dev')
        self.assertIn(feedback.reference, send.call_args.args[1])


class ToolTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='viewer')

    def test_data_tools_refused_without_access(self):
        ctx = tools.ToolContext(user=None, data_allowed=False, reason='not linked')
        for name in tools.DATA_TOOLS:
            with self.assertRaisesMessage(tools.ToolError, 'not linked'):
                tools.run(name, {'query': 'x', 'work_order': 'x', 'page': 'clients'}, ctx)

    def test_django_permissions_enforced(self):
        ctx = tools.ToolContext(user=self.user, data_allowed=True)
        with self.assertRaises(tools.ToolError):
            tools.run('find_work_orders', {}, ctx)
        self.user.user_permissions.add(Permission.objects.get(codename='view_workorder'))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        ctx.user = self.user
        self.assertEqual(tools.run('find_work_orders', {'query': 'nothing'}, ctx), 'No matching work orders.')

    def test_docs_cannot_escape_or_open_hidden_pages(self):
        ctx = tools.ToolContext()
        for name in ['../config/settings', 'docker-server', 'feishu-login', 'missing-doc']:
            with self.assertRaises(tools.ToolError):
                tools.run('read_doc', {'name': name}, ctx)
        self.assertIn('COR', tools.run('read_doc', {'name': 'cor-reader'}, ctx))
        self.assertNotIn('docker-server', dict(tools.doc_index()))


class ParseTests(TestCase):
    @patch('feishu_bot.feishu_api.bot_open_id', return_value='ou_bot')
    def test_rich_text_post(self, _):
        content = {'title': '', 'content': [[{'tag': 'at', 'user_name': 'BMS'}, {'tag': 'text', 'text': ' 1. finance'}],
                                            [{'tag': 'img', 'image_key': 'img_1'}]]}
        text, images = feishu_api.parse_content('post', content)
        self.assertEqual(text, '@BMS 1. finance')
        self.assertEqual(images, ['img_1'])

    def test_card_dividers(self):
        built = feishu_api.card('Thanks!\n---\n**Two quick checks**')
        self.assertEqual([e['tag'] for e in built['elements']], ['markdown', 'hr', 'markdown'])


def block(**kw):
    return NS(**kw)


@override_settings(FEISHU_BOT_BACKEND='api')
class AgentLoopTests(TestCase):
    def test_tool_round_trip_keeps_assistant_turn_unchanged(self):
        first = NS(stop_reason='tool_use', content=[
            block(type='thinking', thinking=''),
            block(type='tool_use', id='tu_1', name='read_doc', input={'name': 'cor-reader'})])
        second = NS(stop_reason='end_turn', content=[block(type='text', text='The COR reader...')])
        fake = MagicMock()
        fake.beta.messages.create.side_effect = [first, second]
        with patch('feishu_bot.agent.anthropic_client', return_value=fake):
            answer = agent.respond([], [{'type': 'text', 'text': 'how does COR work?'}], tools.ToolContext(), 'p2p')
        self.assertEqual(answer, 'The COR reader...')
        sent = fake.beta.messages.create.call_args_list[1].kwargs['messages']
        self.assertIs(sent[1]['content'], first.content)
        self.assertEqual(sent[2]['content'][0]['tool_use_id'], 'tu_1')
        self.assertNotIn('is_error', sent[2]['content'][0])
        kwargs = fake.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs['fallbacks'], 'default')
        self.assertNotIn('thinking', kwargs)

    def test_refusal(self):
        fake = MagicMock()
        fake.beta.messages.create.return_value = NS(stop_reason='refusal', content=[])
        with patch('feishu_bot.agent.anthropic_client', return_value=fake):
            self.assertIn("can't help", agent.respond([], [{'type': 'text', 'text': 'x'}], tools.ToolContext(), 'p2p'))


@override_settings(FEISHU_BOT_BACKEND='claude-cli', FEISHU_BOT_DASHBOARD_USERNAME='')
class ClaudeCliBackendTests(TestCase):
    def run_cli(self, stdout):
        done = NS(stdout=stdout, stderr='', returncode=0)
        with patch('feishu_bot.claude_cli.executable', return_value='claude'), \
                patch('feishu_bot.claude_cli.subprocess.run', return_value=done) as run:
            answer = agent.respond([{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello'}],
                                   [{'type': 'text', 'text': 'how does COR work?'}], tools.ToolContext(), 'p2p')
        return answer, run.call_args

    def test_isolated_docs_only_call(self):
        result = json.dumps({'type': 'result', 'is_error': False, 'result': 'The COR reader...'})
        answer, call = self.run_cli('{"type": "system"}\n' + result + '\n')
        self.assertEqual(answer, 'The COR reader...')
        command = call.args[0]
        self.assertEqual(command[command.index('--tools') + 1], '')
        self.assertIn('--strict-mcp-config', command)
        self.assertEqual(command[command.index('--setting-sources') + 1], '')
        self.assertEqual(command[command.index('--allowedTools') + 1:command.index('--allowedTools') + 4],
                         ['mcp__ebir__read_doc', 'mcp__ebir__record_feedback', 'mcp__ebir__view_dashboard_page'])
        self.assertNotIn('ANTHROPIC_API_KEY', call.kwargs['env'])
        sent = json.loads(call.kwargs['input'])['message']['content']
        self.assertIn('Assistant: Hello', sent[0]['text'])
        self.assertIn('live dashboard access is not configured', sent[1]['text'])
        self.assertEqual(sent[-1]['text'], 'how does COR work?')

    def test_error_becomes_unavailable(self):
        with self.assertRaises(agent.AssistantUnavailable):
            self.run_cli(json.dumps({'type': 'result', 'is_error': True, 'subtype': 'error_during_execution'}))


class DocMcpServerTests(TestCase):
    def test_serves_only_docs_and_feedback(self):
        from feishu_bot.management.commands import feishu_doc_mcp as mcp
        ctx = tools.ToolContext()
        self.assertEqual([t['name'] for t in mcp._tool_list(ctx)], ['read_doc', 'record_feedback'])
        self.assertTrue(mcp._call({'name': 'find_clients', 'arguments': {}}, ctx)['isError'])
        self.assertTrue(mcp._call({'name': 'read_doc', 'arguments': {'name': 'feishu-login'}}, ctx)['isError'])
        self.assertNotIn('isError', mcp._call({'name': 'read_doc', 'arguments': {'name': 'README'}}, ctx))
        self.assertTrue(mcp._call({'name': 'record_feedback', 'arguments': {}}, ctx)['isError'])

    def test_feedback_uses_sender_from_bot_not_model(self):
        from feishu_bot.management.commands import feishu_doc_mcp as mcp
        user = get_user_model().objects.create_user('dhee')
        sender = {'user_id': user.pk, 'open_id': 'ou_dhee', 'name': 'Dhee', 'chat_id': 'oc_1', 'message_id': 'om_1'}
        with patch.dict('os.environ', {'EBIR_BOT_SENDER': json.dumps(sender)}):
            ctx = mcp.sender_context()
        result = mcp._call({'name': 'record_feedback', 'arguments': {
            'category': 'bug', 'summary': 'Export button missing', 'details': 'On the client page.',
            'reporter_name': 'Someone else'}}, ctx)
        self.assertNotIn('isError', result)
        feedback = Feedback.objects.get()
        self.assertIn(feedback.reference, result['content'][0]['text'])
        self.assertEqual((feedback.reporter, feedback.reporter_name, feedback.source_message_id), (user, 'Dhee', 'om_1'))


class LiveDashboardTests(TestCase):
    def test_only_read_only_pages_are_allowed(self):
        from feishu_bot import live_dashboard as live
        uid = '12345678-1234-1234-1234-123456789abc'
        for path in ('/', '/clients/', f'/clients/{uid}/', '/work-orders/', f'/work-orders/{uid}/', '/my-tasks/',
                     '/overview/', '/filings/1601c/', '/clients/?q=shoppal', '/clients/directory/?name=AB%20BROTHERS', '/clients/?tab=all&q=99 ranch&page=2'):
            self.assertTrue(live.allowed(path), path)
        for path in ('/admin/', '/settings/users/', '/logout/', f'/work-orders/{uid}/approve-stage2/',
                     f'/work-orders/{uid}/edit/', f'/work-orders/{uid}/prepared-pdf/', '/my-tasks/notices/read-all/',
                     'https://evil.example/clients/', '//evil.example/', '/clients/?q=<script>', '/api/agent/'):
            self.assertFalse(live.allowed(path), path)

    @override_settings(FEISHU_BOT_SITE_URL='https://dash.test', FEISHU_BOT_DASHBOARD_USERNAME='ner-bot',
                       FEISHU_BOT_DASHBOARD_PASSWORD='pw')
    def test_view_tool_private_only_and_capped(self):
        import tempfile
        from feishu_bot.management.commands import feishu_doc_mcp as mcp
        group = tools.ToolContext()
        self.assertNotIn('view_dashboard_page', [t['name'] for t in mcp._tool_list(group)])
        self.assertTrue(mcp._call({'name': 'view_dashboard_page', 'arguments': {'path': '/clients/'}}, group)['isError'])
        with tempfile.TemporaryDirectory() as folder:
            ctx = tools.ToolContext()
            ctx.screenshot_dir = folder
            self.assertIn('view_dashboard_page', [t['name'] for t in mcp._tool_list(ctx)])
            page = (b'\x89PNG-fake', 'Clients', [('SHOPPAL', '/clients/x/')], ['Nope'])
            with patch('feishu_bot.live_dashboard.view', return_value=page) as view:
                results = [mcp._call({'name': 'view_dashboard_page', 'arguments': {
                    'path': '/clients/', 'highlight': ['View forms', 'Nope']}}, ctx) for _ in range(4)]
            self.assertEqual(view.call_args.args, ('/clients/', ['View forms', 'Nope']))
            self.assertIn('not boxed: Nope', results[0]['content'][1]['text'])
            self.assertEqual(results[0]['content'][0]['type'], 'image')
            self.assertIn('SHOPPAL -> /clients/x/', results[0]['content'][1]['text'])
            self.assertTrue(results[3]['isError'])
            self.assertEqual(len(list(__import__('pathlib').Path(folder).glob('*.png'))), 3)

    def screenshot_flags(self):
        with patch('feishu_bot.claude_cli.respond', return_value='ok') as cli:
            agent.respond([], [{'type': 'text', 'text': 'x'}], tools.ToolContext(), 'p2p')
            agent.respond([], [{'type': 'text', 'text': 'x'}], tools.ToolContext(), 'group')
        return [c.kwargs['screenshots'] for c in cli.call_args_list]

    @override_settings(FEISHU_BOT_BACKEND='claude-cli', FEISHU_BOT_SITE_URL='https://dash.test', FEISHU_BOT_GROUP_DATA=False,
                       FEISHU_BOT_DASHBOARD_USERNAME='ner-bot', FEISHU_BOT_DASHBOARD_PASSWORD='pw')
    def test_screenshots_private_only_by_default(self):
        self.assertEqual(self.screenshot_flags(), [True, False])

    @override_settings(FEISHU_BOT_BACKEND='claude-cli', FEISHU_BOT_SITE_URL='https://dash.test', FEISHU_BOT_GROUP_DATA=True,
                       FEISHU_BOT_DASHBOARD_USERNAME='ner-bot', FEISHU_BOT_DASHBOARD_PASSWORD='pw')
    def test_screenshots_in_groups_when_group_data_enabled(self):
        self.assertEqual(self.screenshot_flags(), [True, True])

    @override_settings(FEISHU_BOT_BACKEND='claude-cli', FEISHU_BOT_SITE_URL='https://dash.test')
    def test_dashboard_paths_become_full_links(self):
        with patch('feishu_bot.claude_cli.respond', return_value='See [the client](/clients/abc/?tab=history).'):
            text = agent.respond([], [{'type': 'text', 'text': 'x'}], tools.ToolContext(), 'p2p')
        self.assertEqual(text, 'See [the client](https://dash.test/clients/abc/?tab=history).')


ROW = {'path': '/work-orders/611fe289-70a5-475e-bd7c-12384d2b3d93/', 'client': 'VIETNEX CORP.', 'reference': 'WO-1',
       'period': '09/2026', 'form': '1601C', 'created_by': 'CHRIS JOHN INDOC', 'needs_review': True}
ROW2 = dict(ROW, path='/work-orders/e6a7bf21-049b-4c71-aefe-dea66013f261/', client='ACME TRADING',
            created_by='admin')


@override_settings(FEISHU_BOT_APPROVAL_CHAT_ID='oc_alerts', FEISHU_BOT_SITE_URL='https://dash.test', FEISHU_BOT_ALERT_MENTIONS=True,
                   FEISHU_BOT_APPROVAL_MENTIONS='chris  john indoc=ou_chris12345; bad=<at id=x>')
@patch('feishu_bot.feishu_api.send_markdown', return_value='om_alert')
class ApprovalAlertTests(TestCase):
    def setUp(self):
        members = patch('feishu_bot.feishu_api.chat_members', return_value=[])  # never call Feishu in tests
        members.start()
        self.addCleanup(members.stop)

    def check(self, rows):
        from feishu_bot import approvals
        with patch('feishu_bot.live_dashboard.awaiting_approvals', return_value=rows):
            return approvals.check_once()

    def test_backlog_summarised_once_then_each_new_one_alone(self, send):
        self.assertEqual(self.check([ROW, ROW2]), 2)
        self.assertEqual(send.call_count, 1)
        self.assertIn('awaiting submission approval (2)', send.call_args.args[1])
        self.assertEqual(self.check([ROW, ROW2]), 0)
        third = dict(ROW, path='/work-orders/27312632-1629-483b-b520-168b0e39f717/', client='NEW CO')
        self.assertEqual(self.check([ROW, ROW2, third]), 1)
        self.assertEqual(send.call_args.args[0], 'oc_alerts')
        self.assertIn('**NEW CO**', send.call_args.args[1])
        self.assertIn('https://dash.test/work-orders/27312632-1629-483b-b520-168b0e39f717/#submission-review',
                      send.call_args.args[1])

    def test_creator_mentioned_when_mapped_else_bold_name(self, send):
        self.check([ROW])
        self.assertIn('Created by <at id=ou_chris12345></at>', send.call_args.args[1])
        self.check([ROW2])
        self.assertIn('Created by **admin**', send.call_args.args[1])

    def test_markup_in_dashboard_text_is_neutralised(self, send):
        self.check([dict(ROW, client='EVIL <at id=ou_everyone1234></at> [x](http://bad)')])
        text = send.call_args.args[1]
        self.assertNotIn('<at id=ou_everyone', text)
        self.assertNotIn('](http://bad)', text)

    def test_failed_post_is_retried_next_time(self, send):
        send.side_effect = [feishu_api.FeishuError('send'), None]
        with self.assertRaises(feishu_api.FeishuError):
            self.check([ROW])
        self.assertEqual(self.check([ROW]), 1)

    def test_test_clients_are_skipped(self, send):
        rows = [dict(ROW2, client=name, path=f'/work-orders/{n:08d}-0000-0000-0000-000000000000/')
                for n, name in enumerate(['Test Company', 'Test Company 2', 'TEST AUTOMATION COMPANY - TEST ONLY'])]
        self.assertEqual(self.check(rows + [ROW, dict(ROW, client='TESTA CORP',
                                                      path='/work-orders/99999999-0000-0000-0000-000000000000/')]), 2)
        text = send.call_args.args[1]
        self.assertIn('VIETNEX CORP.', text)
        self.assertIn('TESTA CORP', text)
        self.assertNotIn('Test Company', text)

    @patch('feishu_bot.feishu_api.chat_members', return_value=[('Chris John Indoc', 'ou_chrisfromgroup1'),
                                                                ('Someone', 'not-an-open-id')])
    def test_creator_matched_to_group_member_by_name(self, members, send):
        with override_settings(FEISHU_BOT_APPROVAL_MENTIONS=''):
            self.check([ROW])
        self.assertIn('Created by <at id=ou_chrisfromgroup1></at>', send.call_args.args[1])

    @patch('feishu_bot.feishu_api.chat_members', side_effect=feishu_api.FeishuError('member list'))
    def test_member_list_failure_falls_back_to_bold_name(self, members, send):
        with override_settings(FEISHU_BOT_APPROVAL_MENTIONS=''):
            self.check([ROW])
        self.assertIn('Created by **CHRIS JOHN INDOC**', send.call_args.args[1])


WORKER = {'name': 'HYPERV-EBIR', 'online': True, 'connection': 'Online', 'activity': 'Idle',
          'heartbeat': 'Heartbeat 1:58:38 PM 05 Oct 2026'}
DOWN = dict(WORKER, online=False, connection='No recent heartbeat', activity='Activity unknown')


@override_settings(FEISHU_BOT_WORKER_ALERT_TO=['ou_heiner12345'], FEISHU_BOT_SITE_URL='https://dash.test')
@patch('feishu_bot.feishu_api.send_markdown', return_value='om_worker')
class WorkerAlertTests(TestCase):
    def check(self, workers):
        from feishu_bot import worker_alerts
        with patch('feishu_bot.live_dashboard.worker_statuses', return_value=workers):
            return worker_alerts.check_once()

    def test_offline_then_back_online_reported_once_each_privately(self, send):
        self.assertEqual(self.check([WORKER]), 0)  # first sighting online: remembered quietly
        self.assertEqual(self.check([DOWN]), 1)
        self.assertEqual(send.call_args.args[0], 'ou_heiner12345')
        self.assertEqual(send.call_args.kwargs, {'id_type': 'open_id'})
        self.assertIn('Worker offline: HYPERV-EBIR', send.call_args.args[1])
        self.assertIn('No recent heartbeat', send.call_args.args[1])
        self.assertEqual(self.check([DOWN]), 0)  # still offline: no repeat
        self.assertEqual(self.check([WORKER]), 1)
        self.assertIn('Worker back online: HYPERV-EBIR', send.call_args.args[1])
        self.assertEqual(send.call_count, 2)

    def test_worker_already_offline_when_first_seen_is_reported(self, send):
        self.assertEqual(self.check([DOWN]), 1)

    def test_failed_send_is_retried(self, send):
        self.check([WORKER])
        send.side_effect = [feishu_api.FeishuError('send'), 'om_worker']
        with self.assertRaises(feishu_api.FeishuError):
            self.check([DOWN])
        self.assertEqual(self.check([DOWN]), 1)


class MonitorTests(TestCase):
    @override_settings(FEISHU_BOT_APPROVAL_CHAT_ID='oc_x', FEISHU_BOT_WORKER_ALERT_TO=['ou_heiner12345'],
                       FEISHU_BOT_SITE_URL='https://dash.test', FEISHU_BOT_DASHBOARD_USERNAME='ner-bot',
                       FEISHU_BOT_DASHBOARD_PASSWORD='pw')
    def test_enabled_checks_follow_settings(self):
        from feishu_bot import monitor
        self.assertEqual([name for name, _ in monitor.checks()], ['approval', 'package', 'worker'])
        with override_settings(FEISHU_BOT_APPROVAL_CHAT_ID='', FEISHU_BOT_WORKER_ALERT_TO=[]):
            self.assertEqual(monitor.checks(), [])


PACKAGE = dict(ROW, path='/work-orders/aaaaaaaa-0000-0000-0000-000000000001/', client='XPAND BOOM TECHNOLOGY CORP.',
               status='Receipt package generated')


@override_settings(FEISHU_BOT_APPROVAL_CHAT_ID='oc_alerts', FEISHU_BOT_SITE_URL='https://dash.test', FEISHU_BOT_ALERT_MENTIONS=True,
                   FEISHU_BOT_APPROVAL_MENTIONS='CHRIS JOHN INDOC=ou_chris12345')
@patch('feishu_bot.feishu_api.send_markdown', return_value='om_package')
class PackageAlertTests(TestCase):
    def setUp(self):
        members = patch('feishu_bot.feishu_api.chat_members', return_value=[])
        members.start()
        self.addCleanup(members.stop)

    def check(self, rows):
        from feishu_bot import packages
        with patch('feishu_bot.live_dashboard.completed_packages', return_value=rows):
            return packages.check_once()

    def test_existing_packages_recorded_quietly_then_new_ones_announced(self, send):
        self.assertEqual(self.check([PACKAGE]), 0)
        self.assertEqual(self.check([]), 0)
        send.assert_not_called()
        new = dict(PACKAGE, path='/work-orders/aaaaaaaa-0000-0000-0000-000000000002/', client='VIETNEX CORP.')
        self.assertEqual(self.check([PACKAGE, new]), 1)
        text = send.call_args.args[1]
        self.assertEqual(send.call_args.args[0], 'oc_alerts')
        self.assertIn('Full filing package ready', text)
        self.assertIn('**VIETNEX CORP.**', text)
        self.assertIn('created by <at id=ou_chris12345></at>', text)
        self.assertIn('https://dash.test/work-orders/aaaaaaaa-0000-0000-0000-000000000002/', text)
        self.assertEqual(self.check([PACKAGE, new]), 0)

    def test_empty_first_run_still_counts_as_first(self, send):
        self.check([])
        self.assertEqual(self.check([PACKAGE]), 1)

    def test_simulations_and_test_clients_skipped(self, send):
        self.check([])
        sim = dict(PACKAGE, status='Simulation complete - package generated')
        test = dict(PACKAGE, path='/work-orders/aaaaaaaa-0000-0000-0000-000000000003/', client='Test Company 2')
        self.assertEqual(self.check([sim, test]), 0)
        send.assert_not_called()

    @override_settings(FEISHU_BOT_ALERT_MENTIONS=False)
    def test_mentions_switched_off_shows_bold_name(self, send):
        self.check([PACKAGE])  # first run: recorded quietly
        new = dict(PACKAGE, path='/work-orders/aaaaaaaa-0000-0000-0000-000000000009/', client='NEW CO')
        self.check([PACKAGE, new])
        self.assertIn('created by **CHRIS JOHN INDOC**', send.call_args.args[1])
        self.assertNotIn('<at id=', send.call_args.args[1])
