"""Thin wrapper over the Feishu IM API. Never logs message content or credentials."""
import io
import json
import logging
import re
import uuid

from django.conf import settings

log = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class FeishuError(Exception):
    pass


_client = None


def client():
    global _client
    if _client is None:
        import lark_oapi as lark
        _client = (lark.Client.builder().app_id(settings.FEISHU_BOT_APP_ID)
                   .app_secret(settings.FEISHU_BOT_APP_SECRET).log_level(lark.LogLevel.WARNING).build())
    return _client


def _check(response, action):
    if not response.success():
        log.warning('Feishu %s failed: code=%s', action, response.code)
        raise FeishuError(action)
    return response


def card(markdown):
    """An interactive card; a line of only '---' becomes a divider, as in Feishu's own bots."""
    elements = []
    for part in re.split(r'(?m)^\s*---+\s*$', markdown):
        if part.strip():
            if elements:
                elements.append({'tag': 'hr'})
            elements.append({'tag': 'markdown', 'content': part.strip()})
    # update_multi lets the bot replace the card later (the "Looking into it" placeholder becomes the answer).
    return {'config': {'wide_screen_mode': True, 'update_multi': True},
            'elements': elements or [{'tag': 'markdown', 'content': ' '}]}


def reply(message_id, msg_type, content):
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody
    request = (ReplyMessageRequest.builder().message_id(message_id)
               .request_body(ReplyMessageRequestBody.builder().msg_type(msg_type)
                             .content(json.dumps(content, ensure_ascii=False)).uuid(str(uuid.uuid4())).build())
               .build())
    return _check(client().im.v1.message.reply(request), 'reply').data.message_id


def reply_markdown(message_id, markdown):
    return reply(message_id, 'interactive', card(markdown))


def update_markdown(message_id, markdown):
    """Replace the content of a card this bot sent."""
    from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
    request = (PatchMessageRequest.builder().message_id(message_id)
               .request_body(PatchMessageRequestBody.builder()
                             .content(json.dumps(card(markdown), ensure_ascii=False)).build())
               .build())
    _check(client().im.v1.message.patch(request), 'update')


def send_markdown(receive_id, markdown, id_type='chat_id'):
    """Post a card to a chat, or with id_type='open_id' privately to one person."""
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    request = (CreateMessageRequest.builder().receive_id_type(id_type)
               .request_body(CreateMessageRequestBody.builder().receive_id(receive_id).msg_type('interactive')
                             .content(json.dumps(card(markdown), ensure_ascii=False)).build())
               .build())
    return _check(client().im.v1.message.create(request), 'send').data.message_id


def delete_message(message_id):
    """Recall a message this bot sent."""
    from lark_oapi.api.im.v1 import DeleteMessageRequest
    _check(client().im.v1.message.delete(DeleteMessageRequest.builder().message_id(message_id).build()), 'delete')


def chat_members(chat_id):
    """[(name, open_id)] of a group's members (needs im:chat.members:read)."""
    from lark_oapi.api.im.v1 import GetChatMembersRequest
    members, token = [], None
    for _ in range(20):
        builder = GetChatMembersRequest.builder().chat_id(chat_id).member_id_type('open_id').page_size(100)
        data = _check(client().im.v1.chat_members.get((builder.page_token(token) if token else builder).build()),
                      'member list').data
        members += [(m.name or '', m.member_id or '') for m in data.items or []]
        if not data.has_more:
            break
        token = data.page_token
    return members


def upload_image(data):
    from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
    request = (CreateImageRequest.builder()
               .request_body(CreateImageRequestBody.builder().image_type('message').image(io.BytesIO(data)).build())
               .build())
    return _check(client().im.v1.image.create(request), 'image upload').data.image_key


def download_image(message_id, image_key):
    from lark_oapi.api.im.v1 import GetMessageResourceRequest
    request = GetMessageResourceRequest.builder().message_id(message_id).file_key(image_key).type('image').build()
    data = _check(client().im.v1.message_resource.get(request), 'image download').file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise FeishuError('image too large')
    return data


def get_message(message_id):
    """(sender_type, msg_type, content dict) for a message, e.g. the one a user replied to."""
    from lark_oapi.api.im.v1 import GetMessageRequest
    request = GetMessageRequest.builder().message_id(message_id).build()
    items = _check(client().im.v1.message.get(request), 'message lookup').data.items or []
    if not items:
        raise FeishuError('message lookup')
    item = items[0]
    try:
        content = json.loads(item.body.content or '{}')
    except ValueError:
        content = {}
    return (item.sender.sender_type if item.sender else ''), item.msg_type, content


def parse_content(msg_type, content, mentions=()):
    """Plain text plus image keys. Mention placeholders become names; the bot's own is removed."""
    text, images = '', []
    if msg_type == 'text':
        text = content.get('text', '')
    elif msg_type == 'post':
        post = content
        if 'content' not in post:  # localised form: {"zh_cn": {...}}
            post = next((v for v in content.values() if isinstance(v, dict)), {})
        lines = [post.get('title', '')] if post.get('title') else []
        for paragraph in post.get('content') or []:
            parts = []
            for node in paragraph:
                tag = node.get('tag')
                if tag in {'text', 'a', 'md'}:
                    parts.append(node.get('text', ''))
                elif tag == 'at':
                    parts.append('@' + (node.get('user_name') or ''))
                elif tag == 'img' and node.get('image_key'):
                    images.append(node['image_key'])
                elif tag == 'code_block':
                    parts.append(node.get('text', ''))
            lines.append(''.join(parts))
        text = '\n'.join(lines)
    elif msg_type == 'image':
        if content.get('image_key'):
            images.append(content['image_key'])
    elif msg_type == 'interactive':
        text = json.dumps(content, ensure_ascii=False)[:4000]
    for mention in mentions or ():
        key = getattr(mention, 'key', None)
        if key:
            name = getattr(mention, 'name', '') or ''
            is_bot = getattr(getattr(mention, 'id', None), 'open_id', None) == bot_open_id()
            text = text.replace(key, '' if is_bot else '@' + name)
    return re.sub(r'[ \t]+', ' ', text).strip(), images


_names = {}


def user_name(open_id):
    """Display name via the contact API (needs contact:user.base:readonly); '' when not permitted."""
    if open_id not in _names:
        from lark_oapi.api.contact.v3 import GetUserRequest
        request = GetUserRequest.builder().user_id(open_id).user_id_type('open_id').build()
        response = client().contact.v3.user.get(request)
        user = response.data.user if response.success() and response.data else None
        _names[open_id] = (getattr(user, 'name', '') or '') if user else ''
    return _names[open_id]


_bot_open_id = None


def bot_open_id():
    global _bot_open_id
    if _bot_open_id is None:
        import lark_oapi as lark
        request = (lark.BaseRequest.builder().http_method(lark.HttpMethod.GET).uri('/open-apis/bot/v3/info')
                   .token_types({lark.AccessTokenType.TENANT}).build())
        try:
            body = json.loads(client().request(request).raw.content)
            _bot_open_id = body['bot']['open_id']
        except (KeyError, TypeError, ValueError, AttributeError):
            log.warning('Could not read the bot identity; mentions of the bot will be shown as names.')
            _bot_open_id = ''
    return _bot_open_id
