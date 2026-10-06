"""Turn one im.message.receive_v1 event into an assistant reply."""
import base64
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from . import agent, feishu_api, tools
from .models import BotMessage

log = logging.getLogger(__name__)

HISTORY_TURNS = 20
PRIVATE_MEMORY = timedelta(hours=12)
MAX_IMAGES = 3
THINKING = '⏳ Looking into it…'


def _media_type(data):
    if data.startswith(b'\x89PNG'):
        return 'image/png'
    if data.startswith(b'\xff\xd8'):
        return 'image/jpeg'
    if data[:4] == b'GIF8':
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _linked_user(open_id, tenant_key):
    from accounts.models import FeishuIdentity
    identity = (FeishuIdentity.objects.select_related('user')
                .filter(app_id=settings.FEISHU_BOT_APP_ID, tenant_key=tenant_key, open_id=open_id).first())
    return identity.user if identity and identity.user.is_active else None


def _history(thread_key, chat_type, exclude_id):
    turns = BotMessage.objects.filter(thread_key=thread_key).exclude(message_id=exclude_id)
    if chat_type == 'p2p':
        turns = turns.filter(created_at__gte=timezone.now() - PRIVATE_MEMORY)
    turns = list(turns.order_by('-created_at', '-pk')[:HISTORY_TURNS])[::-1]
    messages = []
    for turn in turns:
        text = turn.text if turn.role == 'assistant' or chat_type == 'p2p' else f'{turn.sender_name or "Someone"}: {turn.text}'
        if messages and messages[-1]['role'] == turn.role:
            messages[-1]['content'] += '\n\n' + text
        else:
            messages.append({'role': turn.role, 'content': text})
    while messages and messages[0]['role'] != 'user':
        messages.pop(0)
    # The current message is the next user turn, so the history must end with the assistant.
    if messages and messages[-1]['role'] == 'user':
        messages.append({'role': 'assistant', 'content': '(no reply was sent)'})
    return messages


def _quoted(parent_id):
    if not parent_id or BotMessage.objects.filter(message_id=parent_id).exists():
        return ''
    try:
        sender_type, msg_type, content = feishu_api.get_message(parent_id)
    except feishu_api.FeishuError:
        return ''
    text, _ = feishu_api.parse_content(msg_type, content)
    return f'[Quoted message being replied to]\n{text[:4000]}' if text else ''


def _bot_mentioned(mentions):
    bot = feishu_api.bot_open_id()
    return any((getattr(getattr(m, 'id', None), 'open_id', None) == bot) if bot else True for m in mentions or [])


def handle(data):
    close_old_connections()
    try:
        _handle(data)
    except Exception:
        log.exception('Feishu message handling failed')
    finally:
        close_old_connections()


def _handle(data):
    event = data.event
    sender, msg = event.sender, event.message
    open_id = getattr(sender.sender_id, 'open_id', '') or ''
    if sender.sender_type != 'user' or not open_id:
        return
    if settings.FEISHU_BOT_TENANT_KEY and sender.tenant_key != settings.FEISHU_BOT_TENANT_KEY:
        log.info('Skipped message %s: other tenant', msg.message_id)
        return
    if msg.chat_type != 'p2p' and not _bot_mentioned(msg.mentions):
        log.info('Skipped group message %s: assistant not mentioned', msg.message_id)
        return
    try:
        content = json.loads(msg.content or '{}')
    except ValueError:
        content = {}
    text, image_keys = feishu_api.parse_content(msg.message_type, content, msg.mentions)
    if not text and not image_keys:
        if not msg.parent_id:
            log.info('Skipped message %s: no text (type %s)', msg.message_id, msg.message_type)
            return
        # A bare "@Ner" reply points the assistant at the message being replied to (added below as a quote).
        text = '(Please answer the quoted message.)'

    user = _linked_user(open_id, sender.tenant_key)
    name = (user.get_full_name() or user.first_name) if user else ''
    name = name or feishu_api.user_name(open_id)
    thread_key = msg.chat_id if msg.chat_type == 'p2p' else (msg.root_id or msg.message_id)
    try:
        with transaction.atomic():
            BotMessage.objects.create(message_id=msg.message_id, thread_key=thread_key, chat_id=msg.chat_id,
                                      chat_type=msg.chat_type, role='user', sender_open_id=open_id,
                                      sender_name=name[:150], text=(text or '[image]')[:20000])
    except IntegrityError:
        return  # Feishu redelivered an event we already handled.
    log.info('Answering %s message %s', msg.chat_type, msg.message_id)

    recent = BotMessage.objects.filter(sender_open_id=open_id, role='user',
                                       created_at__gte=timezone.now() - timedelta(hours=1)).count()
    if recent > settings.FEISHU_BOT_HOURLY_LIMIT:
        feishu_api.reply_markdown(msg.message_id, "I've had a lot of messages from you this hour. Please try again a little later.")
        return

    if user is None:
        reason = 'the sender has not signed in to the dashboard with Feishu, so their account is not linked'
    elif msg.chat_type != 'p2p' and not settings.FEISHU_BOT_GROUP_DATA:
        reason = 'this is a group chat; client data is only shared in a private chat with the assistant'
    else:
        reason = ''
    ctx = tools.ToolContext(user=user, data_allowed=not reason, reason=reason, sender_open_id=open_id,
                            sender_name=name, chat_id=msg.chat_id, message_id=msg.message_id)

    blocks = []
    quoted = _quoted(msg.parent_id)
    if quoted:
        blocks.append({'type': 'text', 'text': quoted})
    for key in image_keys[:MAX_IMAGES]:
        try:
            image = feishu_api.download_image(msg.message_id, key)
        except feishu_api.FeishuError:
            continue
        media_type = _media_type(image)
        if media_type:
            blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': media_type,
                                                        'data': base64.standard_b64encode(image).decode()}})
    speaker = f'{name}: ' if msg.chat_type != 'p2p' and name else ''
    blocks.append({'type': 'text', 'text': speaker + (text or '(sent an image)')})

    # Bots cannot show "typing…", so post a placeholder now and replace it with the answer.
    try:
        placeholder_id = feishu_api.reply_markdown(msg.message_id, THINKING)
    except feishu_api.FeishuError:
        placeholder_id = None
    try:
        answer = agent.respond(_history(thread_key, msg.chat_type, msg.message_id), blocks, ctx, msg.chat_type)
    except agent.AssistantUnavailable as exc:
        log.warning('Claude request failed: %s', exc)
        answer = "Sorry, I couldn't reach the assistant service just now. Please try again in a minute."

    reply_id = _deliver(msg.message_id, placeholder_id, answer)
    BotMessage.objects.create(message_id=reply_id or f'reply-{msg.message_id}', thread_key=thread_key,
                              chat_id=msg.chat_id, chat_type=msg.chat_type, role='assistant', text=answer[:20000])
    for png in ctx.images:
        try:
            feishu_api.reply(msg.message_id, 'image', {'image_key': feishu_api.upload_image(png)})
        except feishu_api.FeishuError:
            feishu_api.reply_markdown(msg.message_id, 'The screenshot could not be uploaded to Feishu.')
    for feedback in ctx.feedback:
        _notify(feedback, msg.chat_id)


def _deliver(message_id, placeholder_id, answer):
    if placeholder_id:
        try:
            feishu_api.update_markdown(placeholder_id, answer)
            return placeholder_id
        except feishu_api.FeishuError:
            pass
    return feishu_api.reply_markdown(message_id, answer)


def _notify(feedback, source_chat):
    target = settings.FEISHU_BOT_FEEDBACK_CHAT_ID
    if not target or target == source_chat:
        return
    try:
        feishu_api.send_markdown(target, (
            f'**New feedback {feedback.reference}** ({feedback.get_category_display()})\n'
            f'From: {feedback.reporter_name or "unknown"}\n\n**{feedback.summary}**\n\n{feedback.details}'))
    except feishu_api.FeishuError:
        pass
