"""
title: Ping Tung
author: tito
version: 0.1.0
description: Gọi Tùng (người thật) khi cần hỗ trợ gấp qua Discord webhook.
"""

import asyncio
import json
import os
import time
import logging
import secrets
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

MAX_MESSAGE_CHARS = 300
RATE_LIMIT_SECONDS = 600  # 10 minutes

# chat_id -> epoch seconds of the last successful ping (in-memory).
_LAST_PING: dict[str, float] = {}

SUCCESS = 'Đã nhắn Tùng.'
RATE_LIMITED = 'Đã nhắn Tùng rồi, đang chờ.'
ERROR = 'Chưa nhắn được Tùng (mã {code}).'
USER_AGENT = (
    'TitoBot (https://titodori.duckdns.org, 1.0)'  # Cloudflare blocks the default Python-urllib UA (403, error 1010)
)
log = logging.getLogger(__name__)


def _incident(detail: str) -> str:
    """Log one TITO-ERR line and return its code (no URLs or tokens in detail)."""
    code = f'T{datetime.now(ZoneInfo("America/Los_Angeles")):%H%M}-{secrets.token_hex(2)}'
    log.error('TITO-ERR %s ping_tony %s', code, detail)
    return code


def _message_text(message: dict) -> str:
    content = message.get('content') if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get('text'), str):
                parts.append(item['text'])
        return ' '.join(parts)
    return '' if content is None else str(content)


def _truncate(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    return text[:limit]


def _recent_messages(messages: list, limit: int = 3) -> list[tuple[str, str]]:
    rows = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        if role not in ('user', 'assistant'):
            continue
        rows.append((role, _truncate(_message_text(message))))
    return rows[-limit:]


def _post_discord_webhook(url: str, payload: dict) -> bool:
    """POST one Discord webhook JSON message. Returns True on a 2xx response."""
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return 200 <= resp.status < 300


class Tools:
    class Valves(BaseModel):
        # Urgent channel for real pings; falls back to the general log webhook.
        discord_webhook_url: str = os.getenv('TITO_URGENT_WEBHOOK', '') or os.getenv('TITO_DISCORD_WEBHOOK', '')
        admin_base_url: str = 'https://185-147-159-26.sslip.io'
        # Discord user id to @mention (notifies even in a muted channel). Set via valves, not in git.
        ping_user_id: str = os.getenv('TITO_DISCORD_PING_USER_ID', '')

    def __init__(self):
        self.valves = self.Valves()

    async def ping_tony(
        self,
        reason: str,
        urgency: str = 'normal',
        __user__: dict = None,
        __metadata__: dict = None,
        __messages__: list = None,
    ) -> str:
        """
        Nhắn Tùng (người thật) qua Discord khi người dùng cần một con người hỗ trợ.

        Dùng khi:
        - Người dùng cần nói chuyện với người thật (Tùng) thay vì trợ lý.
        - Việc khẩn cấp / "hotline" (cần phản hồi ngay từ con người).
        - Trợ lý bị kẹt, không trả lời được, hoặc người dùng yêu cầu hỗ trợ con người.

        ``reason`` là lý do ngắn gọn; ``urgency`` là mức khẩn (vd "normal", "urgent").
        Mỗi cuộc trò chuyện chỉ được nhắn tối đa 1 lần trong 10 phút.
        """
        url = self.valves.discord_webhook_url or ''
        if not url:
            return ERROR.format(code=_incident('webhook url empty'))

        metadata = __metadata__ or {}
        chat_id = metadata.get('chat_id') or ''

        now = time.time()
        last = _LAST_PING.get(chat_id)
        if last is not None and now - last < RATE_LIMIT_SECONDS:
            return RATE_LIMITED

        who = (__user__ or {}).get('name') or 'unknown'

        admin_base = (self.valves.admin_base_url or '').rstrip('/')
        link = f'{admin_base}/c/{chat_id}' if chat_id else ''

        lines = [
            f'Người nhắn: {who}',
            f'Mức khẩn: {urgency}',
            f'Lý do: {reason}',
        ]
        for role, text in _recent_messages(__messages__):
            lines.append(f'{role}: {text}')
        if link:
            lines.append(f'Link chat: {link}')

        uid = ''.join(ch for ch in (self.valves.ping_user_id or '') if ch.isdigit())
        if uid:
            lines.insert(0, f'<@{uid}> 🚨 Tito cần Tùng')
        payload = {
            'content': '\n'.join(lines),
            'username': 'Ping Tung',
            # Only Tùng can be pinged; nothing in the chat text can @everyone.
            'allowed_mentions': {'parse': [], 'users': [uid] if uid else []},
        }

        detail = 'non-2xx'
        try:
            posted = await asyncio.to_thread(_post_discord_webhook, url, payload)
        except urllib.error.HTTPError as e:
            posted, detail = False, f'http {e.code}'
        except Exception as e:
            posted, detail = False, type(e).__name__

        if posted:
            _LAST_PING[chat_id] = now
            return SUCCESS
        return ERROR.format(code=_incident(detail))
