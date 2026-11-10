import re
"""Tests for the standalone ``ping_tony`` Open WebUI Tool (TASK B).

The tool lives at ``tito-deploy/tools/ping_tony.py`` and is installed later via
the admin API, so these tests load it by file path (importlib) rather than as a
package import. They monkeypatch the HTTP call, so no network is touched.
"""

import asyncio
import importlib.util
from pathlib import Path

# Repo root is 4 parents up from backend/open_webui/test/tito/test_ping_tony.py.
_TOOL_PATH = Path(__file__).resolve().parents[4] / 'tito-deploy' / 'tools' / 'ping_tony.py'

_spec = importlib.util.spec_from_file_location('ping_tony', _TOOL_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

SUCCESS = 'Đã nhắn Tùng.'
RATE_LIMITED = 'Đã nhắn Tùng rồi, đang chờ.'
ERROR = 'Chưa nhắn được Tùng (mã {code}).'
ERROR_RE = r'^Chưa nhắn được Tùng \(mã T\d{4}-[0-9a-f]{4}\)\.$'

WEBHOOK = 'https://discord.example/api/webhooks/1/2'
ADMIN_BASE = 'https://185-147-159-26.sslip.io'


def _make_tools(monkeypatch, webhook=WEBHOOK):
    monkeypatch.setattr(module, '_LAST_PING', {})
    tools = module.Tools()
    tools.valves.discord_webhook_url = webhook
    tools.valves.admin_base_url = ADMIN_BASE
    return tools


def _capture(monkeypatch, result=True):
    captured = {}

    def fake_post(url, payload):
        captured['url'] = url
        captured['payload'] = payload
        return result

    monkeypatch.setattr(module, '_post_discord_webhook', fake_post)
    return captured


def test_returns_no_tony_anywhere():
    # SOURCE: brief TASK B — the word "Tony" must never appear in any returned string.
    for text in (SUCCESS, RATE_LIMITED, ERROR):
        assert 'Tony' not in text and 'tony' not in text


def test_success_posts_payload_and_returns_vietnamese(monkeypatch):
    # SOURCE: brief TASK B — success returns "Đã nhắn Tùng." and posts who/urgency/
    # reason/last-messages/link.
    captured = _capture(monkeypatch, result=True)
    tools = _make_tools(monkeypatch)

    messages = [
        {'role': 'system', 'content': 'ignore me'},
        {'role': 'user', 'content': 'alo'},
        {'role': 'assistant', 'content': 'chào'},
    ]
    out = asyncio.run(
        tools.ping_tony(
            'khẩn cấp',
            urgency='urgent',
            __user__={'name': 'Alice', 'email': 'secret@example.com'},
            __metadata__={'chat_id': 'c123'},
            __messages__=messages,
        )
    )

    assert out == SUCCESS
    assert captured['url'] == WEBHOOK
    content = captured['payload']['content']
    assert 'Alice' in content
    assert 'urgent' in content
    assert 'khẩn cấp' in content
    assert f'{ADMIN_BASE}/c/c123' in content
    # system message excluded; user/assistant included
    assert 'ignore me' not in content
    assert 'alo' in content and 'chào' in content


def test_payload_excludes_email(monkeypatch):
    # SOURCE: brief TASK B — never include tokens/emails beyond the display name.
    captured = _capture(monkeypatch, result=True)
    tools = _make_tools(monkeypatch)
    asyncio.run(
        tools.ping_tony(
            'x',
            __user__={'name': 'Bob', 'email': 'bob@secret.example', 'api_key': 'tok'},
            __metadata__={'chat_id': 'c9'},
        )
    )
    content = captured['payload']['content']
    assert 'Bob' in content
    assert 'bob@secret.example' not in content
    assert 'tok' not in content


def test_truncates_messages_to_300_and_keeps_last_3(monkeypatch):
    # SOURCE: brief TASK B — last 3 user/assistant messages, each truncated to 300 chars.
    long = 'x' * 1000
    messages = [
        {'role': 'user', 'content': 'm1'},
        {'role': 'assistant', 'content': 'm2'},
        {'role': 'user', 'content': long},
        {'role': 'assistant', 'content': 'm4'},
    ]
    rows = module._recent_messages(messages)
    assert [role for role, _ in rows] == ['assistant', 'user', 'assistant']
    assert rows[1][1] == long[:300]
    assert len(rows[1][1]) == 300

    captured = _capture(monkeypatch, result=True)
    tools = _make_tools(monkeypatch)
    asyncio.run(tools.ping_tony('x', __metadata__={'chat_id': 'c1'}, __messages__=messages))
    content = captured['payload']['content']
    assert long[:300] in content
    assert long[:301] not in content


def test_rate_limit_one_ping_per_ten_minutes(monkeypatch):
    # SOURCE: brief TASK B — max 1 ping per chat per 10 minutes.
    calls = {'n': 0}

    def fake_post(url, payload):
        calls['n'] += 1
        return True

    monkeypatch.setattr(module, '_post_discord_webhook', fake_post)
    tools = _make_tools(monkeypatch)

    first = asyncio.run(tools.ping_tony('x', __metadata__={'chat_id': 'c1'}))
    second = asyncio.run(tools.ping_tony('x', __metadata__={'chat_id': 'c1'}))
    assert first == SUCCESS
    assert second == RATE_LIMITED
    assert calls['n'] == 1


def test_no_webhook_returns_error(monkeypatch):
    # SOURCE: brief TASK B — no webhook configured -> error string, never raises.
    tools = _make_tools(monkeypatch, webhook='')
    out = asyncio.run(tools.ping_tony('x', __metadata__={'chat_id': 'c1'}))
    assert re.match(ERROR_RE, out), out


def test_http_error_returns_error(monkeypatch):
    # SOURCE: brief TASK B — HTTP error -> error string, never raises.
    def boom(url, payload):
        raise RuntimeError('network down')

    monkeypatch.setattr(module, '_post_discord_webhook', boom)
    tools = _make_tools(monkeypatch)
    out = asyncio.run(tools.ping_tony('x', __metadata__={'chat_id': 'c1'}))
    assert re.match(ERROR_RE, out), out
