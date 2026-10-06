"""Long-connection Feishu bot: the server dials out to Feishu, so no public callback URL is needed."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Run the Feishu assistant bot over a Feishu long connection.'

    def handle(self, *args, **options):
        missing = [name for name in ('FEISHU_BOT_APP_ID', 'FEISHU_BOT_APP_SECRET') if not getattr(settings, name)]
        if settings.FEISHU_BOT_BACKEND == 'claude-cli':
            from feishu_bot import claude_cli
            if not claude_cli.executable():
                missing.append(f'the Claude Code CLI ({settings.FEISHU_BOT_CLAUDE_CLI})')
        elif not os.environ.get('ANTHROPIC_API_KEY'):
            missing.append('ANTHROPIC_API_KEY')
        if missing:
            raise CommandError('Feishu assistant is not configured; missing ' + ', '.join(missing) + '.')
        import logging
        import lark_oapi as lark
        # Bot decisions (never message content) go to the console log alongside the Feishu SDK's.
        logging.basicConfig(level=logging.WARNING, format='[bot] %(asctime)s %(levelname)s %(message)s')
        logging.getLogger('feishu_bot').setLevel(logging.INFO)
        from feishu_bot.handler import handle

        # Feishu expects the event to be acknowledged quickly; Claude answers in a worker thread.
        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='feishu-bot')
        dispatcher = (lark.EventDispatcherHandler.builder('', '')
                      .register_p2_im_message_receive_v1(lambda data: pool.submit(handle, data) and None)
                      # Read receipts, reactions, recalls and "added to a group" arrive if the app subscribes
                      # to them; none needs a reply.
                      .register_p2_im_message_message_read_v1(lambda data: None)
                      .register_p2_im_message_reaction_created_v1(lambda data: None)
                      .register_p2_im_message_reaction_deleted_v1(lambda data: None)
                      .register_p2_im_message_recalled_v1(lambda data: None)
                      .register_p2_im_chat_member_bot_added_v1(lambda data: None)
                      .build())
        from feishu_bot import monitor
        enabled = [name for name, _ in monitor.checks()]
        if enabled:
            threading.Thread(target=monitor.watch, name='dashboard-monitor', daemon=True).start()
            self.stdout.write(f'Alerts on: {", ".join(enabled)} (every {settings.FEISHU_BOT_APPROVAL_POLL_SECONDS}s).')
        self.stdout.write('Feishu assistant connecting...')
        lark.ws.Client(settings.FEISHU_BOT_APP_ID, settings.FEISHU_BOT_APP_SECRET,
                       event_handler=dispatcher, log_level=lark.LogLevel.INFO).start()
