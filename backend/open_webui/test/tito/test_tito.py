"""Red tests for ``open_webui.utils.tito`` (PATCH A / C / G / B5 pure helpers).

These tests FAIL today because ``open_webui.utils.tito`` does not exist yet
(module-level import -> ImportError). They pass only when the module exposes the
exact contract in ``tito-spec/SPEC.md``.

Every expected value names its SOURCE: an existing file:line when one exists,
otherwise the locked plan / vet document / Orc decision that defines the value.
No value is "because the spec says".
"""

import asyncio
import hashlib
import re
import urllib.error
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from open_webui.utils import tito, tito_weather

# --- PATCH G: model gating + locked config ---------------------------------


def test_is_tito_model_true_for_id_tito():
    # SOURCE: brief "all gated on model id 'tito'"; model id field is `model['id']`
    # (backend/open_webui/utils/middleware.py:2192 uses model['id']).
    assert tito.is_tito_model({'id': 'tito'}) is True


def test_is_tito_model_false_for_other_id():
    # SOURCE: brief "other models unchanged" -> any id != 'tito' must be False.
    assert tito.is_tito_model({'id': 'claude-sonnet-5-5'}) is False


def test_tito_features_forces_memory_only():
    # SOURCE: vet B3 — "FORCE features = {memory: true, everything else false}".
    features = tito.tito_features()
    assert features.get('memory') is True
    for key in ('web_search', 'image_generation', 'code_interpreter', 'voice'):
        assert features.get(key, False) is False


def test_lock_background_tasks_wholesale_title_only():
    # SOURCE: Orc O5 — "overwrite background_tasks wholesale {title_generation: true,
    # everything else false}". Task keys are TASKS enum (constants.py:143-145).
    locked = tito.lock_background_tasks(
        {'title_generation': True, 'follow_up_generation': True, 'tags_generation': True}
    )
    assert locked == {'title_generation': True}


def test_lock_background_tasks_empty_input():
    # SOURCE: Orc O5 — wholesale overwrite ignores whatever the client sent.
    assert tito.lock_background_tasks({}) == {'title_generation': True}


def test_tito_stream_options_include_usage():
    # SOURCE: Orc O5 — "pin stream_options.include_usage=true" (vet H6 cost rows).
    assert tito.tito_stream_options() == {'include_usage': True}


def test_tito_max_tokens_pinned():
    # SOURCE: Orc O5 — "pin params.max_tokens (16000)".
    assert tito.TITO_MAX_TOKENS == 16000


# --- PATCH A: memory snapshot (block 2) ------------------------------------


def test_build_memory_snapshot_sorted_plain_no_timestamps():
    # SOURCE: DECISIONS — "all memories, sorted, plain text, no timestamps".
    # Label format `path: content` (else bare content) mirrors memory_label
    # (backend/open_webui/utils/memory.py:43-44).
    memories = [
        SimpleNamespace(id='b', path=None, content='thích Tuấn Ngọc'),
        SimpleNamespace(id='a', path='sức khỏe', content='bảo hiểm 35 đô'),
        SimpleNamespace(id='c', path=None, content='mua xăng ở Fresno'),
    ]
    snapshot = tito.build_memory_snapshot(memories)

    lines = snapshot.split('\n')
    # sorted by (path or '', content or '', id or ''): no-path rows first, then by
    # content code point ('mua...' < 'thích...' since 'm' < 't'), then the path row.
    assert lines[0] == '- mua xăng ở Fresno'
    assert lines[1] == '- thích Tuấn Ngọc'
    assert lines[2] == '- sức khỏe: bảo hiểm 35 đô'
    assert 'updated_at' not in snapshot and 'created_at' not in snapshot


def test_build_memory_snapshot_empty_returns_sentinel():
    # SOURCE: vet M6 — "Write an explicit sentinel when there are none".
    assert tito.build_memory_snapshot([]) == tito.NO_MEMORIES_SENTINEL


def test_build_memory_snapshot_skips_empty_content():
    # SOURCE: MemoryModel.content is a non-null Column (models/memories.py:25),
    # but a row can still hold ''; skip it rather than emit a blank line.
    memories = [
        SimpleNamespace(id='a', path=None, content=''),
        SimpleNamespace(id='b', path=None, content='ok'),
    ]
    assert tito.build_memory_snapshot(memories) == '- ok'


# --- PATCH A: two frozen blocks (block1 + block2) --------------------------


def test_build_tito_blocks_raw_prompt_untemplated():
    # SOURCE: brief PATCH A — "block1 raw Tito prompt ... no {{ }} templating".
    # Orc O7 — block1 and block2 are returned/stored as TWO separate blocks.
    raw = 'Bạn là Tito. Hãy hỏi {{USER_NAME}}?'
    block1, block2 = tito.build_tito_blocks(raw, [SimpleNamespace(id='a', path=None, content='x')])
    assert block1 == raw
    assert '{{USER_NAME}}' in block1  # no substitution happened
    assert tito.SNAPSHOT_HEADING in block2
    assert '- x' in block2


def test_build_tito_blocks_heading_avoids_volatile_markers():
    # SOURCE: vet M5 — the heading must NOT contain the pipe's volatile markers
    # `<memory_context>` (memory.py:17-18) nor `User Context:`.
    assert '<memory_context>' not in tito.SNAPSHOT_HEADING
    assert 'User Context:' not in tito.SNAPSHOT_HEADING


def test_build_tito_blocks_unavailable_uses_unavailable_sentinel():
    # SOURCE: vet M6 — on exception write "(memory unavailable this chat)".
    block1, block2 = tito.build_tito_blocks_unavailable('raw')
    assert block1 == 'raw'
    assert tito.MEMORY_UNAVAILABLE_SENTINEL in block2


def test_freeze_stores_two_blocks_and_sha256():
    # SOURCE: DECISIONS meta.tito_system + sha256; Orc O7 stores block1 AND block2.
    meta = tito.freeze_tito_system({}, 'B1', 'B2')
    assert meta['tito_system']['block1'] == 'B1'
    assert meta['tito_system']['block2'] == 'B2'
    assert meta['tito_system']['sha256'] == hashlib.sha256(b'B1\n\nB2').hexdigest()


def test_get_frozen_returns_combined_and_blocks():
    # SOURCE: Orc O7 — blocks stored separately (pipe breakpoint after block1);
    # combined string is what the messages list carries.
    meta = tito.freeze_tito_system({}, 'B1', 'B2')
    assert tito.get_frozen_tito_system(meta) == 'B1\n\nB2'
    assert tito.get_frozen_tito_blocks(meta) == ('B1', 'B2')


def test_get_frozen_returns_none_when_absent():
    # SOURCE: DECISIONS — freeze only on the FIRST request; absent = first turn.
    assert tito.get_frozen_tito_system({}) is None
    assert tito.get_frozen_tito_blocks({}) is None


def test_sha256_hex_matches_stdlib():
    # SOURCE: hashlib.sha256(...).hexdigest() — the standard digest format.
    assert tito.sha256_hex('abc') == hashlib.sha256(b'abc').hexdigest()


# --- PATCH A: drop/insert of system messages -------------------------------


def test_apply_frozen_system_drops_non_mid_conversation_system_and_prepends():
    # SOURCE: brief PATCH A — "drop every role:system msg (incl Conduit index-0)
    # except mid-conversation status msgs; insert exactly one frozen system".
    messages = [
        {'role': 'system', 'content': 'conduit index-0 system'},
        {'role': 'user', 'content': 'chào'},
        {'role': 'system', 'content': 'status', 'mid_conversation': True},
        {'role': 'assistant', 'content': 'hi'},
    ]
    out = tito.apply_frozen_system(messages, 'FROZEN')
    assert out[0] == {'role': 'system', 'content': 'FROZEN'}
    assert {'role': 'system', 'content': 'status', 'mid_conversation': True} in out
    assert not any(m.get('content') == 'conduit index-0 system' for m in out)


# --- PATCH C: status marker (top-level) + storage in user meta ---------------


def test_build_tito_status_message_is_marked_mid_conversation():
    # SOURCE: Orc C1 — marker is a TOP-LEVEL key: {"role":"system","content":...,
    # "mid_conversation":true}.
    msg = tito.build_tito_status_message('time/location')
    assert msg['role'] == 'system'
    assert msg['content'] == 'time/location'
    assert msg['mid_conversation'] is True


def test_store_tito_status_writes_user_meta():
    # SOURCE: Orc O4 / vet H2 — store the exact status string in the user
    # message's meta (meta.tito_status); meta replays via MESSAGE_REPLAY_KEYS
    # (backend/open_webui/utils/middleware.py:1857).
    user_msg = {'role': 'user', 'content': 'chào', 'meta': {}}
    out = tito.store_tito_status(user_msg, 'status text')
    assert out['meta']['tito_status'] == 'status text'


def test_expand_tito_status_inserts_system_after_user_message():
    # SOURCE: Orc O4 — append the mid_conversation status right AFTER the user msg;
    # expanded from meta.tito_status so replay is byte-identical.
    messages = [
        {'role': 'system', 'content': 'frozen'},
        {'role': 'user', 'content': 'chào', 'meta': {'tito_status': 'S'}},
        {'role': 'assistant', 'content': 'hi'},
    ]
    out = tito.expand_tito_status(messages)
    assert out[1]['role'] == 'user'
    assert out[2] == {'role': 'system', 'content': 'S', 'mid_conversation': True}
    assert out[3]['role'] == 'assistant'


def test_expand_tito_status_noop_without_status_meta():
    # SOURCE: Orc O4 — expansion only applies to user msgs that carry a status.
    messages = [
        {'role': 'user', 'content': 'chào'},
        {'role': 'assistant', 'content': 'hi'},
    ]
    assert tito.expand_tito_status(messages) == messages


# --- PATCH C / O4: status builder ------------------------------------------


def test_build_tito_status_all_vars():
    # SOURCE: Orc O4 — "<context>\ntime: ...\nlocation: ...\n</context>" from
    # CURRENT_DATETIME / CURRENT_TIMEZONE / USER_LOCATION.
    s = tito.build_tito_status(
        {'CURRENT_DATETIME': '2026-11-09', 'CURRENT_TIMEZONE': 'America/Los_Angeles', 'USER_LOCATION': 'Fresno'}
    )
    assert s == '<context>\ntime: 2026-11-09\ntimezone: America/Los_Angeles\nlocation: Fresno\n</context>'


def test_build_tito_status_omits_missing_vars():
    # SOURCE: Orc O4 — "missing → omit that line".
    s = tito.build_tito_status({'CURRENT_DATETIME': '2026-11-09'})
    assert s == '<context>\ntime: 2026-11-09\n</context>'
    assert 'location' not in s and 'timezone' not in s


def test_build_tito_status_budget_hook_empty_by_default():
    # SOURCE: Orc O4 — budget/counters left as a hook arg, empty for now.
    s = tito.build_tito_status({'CURRENT_DATETIME': 'd'})
    assert 'budget' not in s


# --- O3: temporary / missing chat guard ------------------------------------


def test_tito_chat_error_temp_chat_blocked():
    # SOURCE: Orc O3 — block temporary chats for tito (loud fail).
    assert tito.tito_chat_error(None, 'temporary:abc') == tito.TITO_TEMP_CHAT_ERROR


def test_tito_chat_error_missing_chat_not_new():
    # SOURCE: Orc O3 — saved chat_id but no chat row on a follow-up → loud fail.
    assert tito.tito_chat_error(None, 'saved-chat-id', is_new_chat=False) == tito.TITO_NO_CHAT_ERROR


def test_tito_chat_error_ok_new_chat():
    # SOURCE: Orc O3 — a brand-new saved chat legitimately has no row yet (freeze).
    assert tito.tito_chat_error(None, 'saved-chat-id', is_new_chat=True) is None


def test_tito_chat_error_ok_existing_chat():
    # SOURCE: Orc O3 — an existing chat row passes.
    assert tito.tito_chat_error(SimpleNamespace(id='saved-chat-id'), 'saved-chat-id', is_new_chat=False) is None


# --- B5 / O6 / O8: self-check helpers --------------------------------------


def test_tito_required_tool_names_has_memory_and_file():
    # SOURCE: memory tools tools.py:816-827; file tools tools.py:750.
    names = tito.tito_required_tool_names()
    for n in ('search_memories', 'add_memory', 'view_file', 'display_file'):
        assert n in names


def test_tito_missing_tools_none_when_all_present():
    # SOURCE: Orc O6 — self-check asserts expected names are present.
    assert tito.tito_missing_tools(set(tito.tito_required_tool_names())) == []


def test_tito_missing_tools_reports_missing():
    # SOURCE: Orc O6 — missing names surface so the self-check can fail loudly.
    missing = tito.tito_missing_tools({'add_memory'})
    assert 'search_memories' in missing and 'view_file' in missing


def test_tito_model_checks_ok_when_defaults():
    # SOURCE: tools.py:647-648 get_model_capability defaults to True when absent.
    assert tito.tito_model_checks({}) == []


def test_tito_model_checks_flags_disabled_capabilities():
    # SOURCE: Orc O6 — assert model capability memory + file_upload and
    # is_builtin_tool_enabled('memory') (tools.py:652-654, 810).
    model = {
        'info': {
            'meta': {
                'capabilities': {'memory': False, 'file_upload': False},
                'builtinTools': {'memory': False},
            }
        }
    }
    fails = tito.tito_model_checks(model)
    assert len(fails) == 3
    assert any('memory' in f for f in fails)
    assert any('file_upload' in f for f in fails)


def test_tito_config_checks_all_false_ok():
    # SOURCE: Orc O8 — assert ENABLE_PERSISTENT_CONFIG=false,
    # RAG_SYSTEM_CONTEXT=false, memories.system_context.enable=false.
    config = {
        'ENABLE_PERSISTENT_CONFIG': False,
        'RAG_SYSTEM_CONTEXT': False,
        'memories.system_context.enable': False,
    }
    assert tito.tito_config_checks(config) == []


def test_tito_config_checks_flags_truthy():
    # SOURCE: Orc O8 — any truthy value is a loud failure.
    config = {
        'ENABLE_PERSISTENT_CONFIG': True,
        'RAG_SYSTEM_CONTEXT': False,
        'memories.system_context.enable': False,
    }
    fails = tito.tito_config_checks(config)
    assert len(fails) == 1
    assert 'ENABLE_PERSISTENT_CONFIG' in fails[0]


def test_blocks_coerce_none_raw_system_to_empty():
    # N1: no literal "None" text; freeze still round-trips.
    from open_webui.utils import tito

    b1, b2 = tito.build_tito_blocks(None, [])
    assert b1 == '' and 'None' not in b1
    u1, _ = tito.build_tito_blocks_unavailable(None)
    assert u1 == ''
    meta = tito.freeze_tito_system({}, b1, b2)
    assert tito.get_frozen_tito_blocks(meta) == ('', b2)
    assert tito.get_frozen_tito_system(meta) == '\n\n' + b2


def test_frozen_system_join_is_splittable_on_snapshot_heading():
    # N2: pipe splits on first "\n\n" + SNAPSHOT_HEADING.
    from open_webui.utils import tito

    b1, b2 = tito.build_tito_blocks('PROMPT\n\nwith paras', [])
    joined = tito.join_tito_system(b1, b2)
    assert joined == b1 + '\n\n' + tito.SNAPSHOT_HEADING + b2[len(tito.SNAPSHOT_HEADING) :]
    head, sep, tail = joined.partition('\n\n' + tito.SNAPSHOT_HEADING)
    assert head == b1 and sep and (tito.SNAPSHOT_HEADING + tail) == b2
    meta = tito.freeze_tito_system({}, b1, b2)
    assert tito.get_frozen_tito_system(meta) == joined


def test_ensure_status_new_user_message_persists_once():
    # B1: new status stored on message, one status msg inserted, returned for persistence.
    from open_webui.utils import tito

    msgs = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}]
    out, persist = tito.ensure_tito_status(msgs, 'ST')
    assert persist == 'ST'
    assert out[1]['meta']['tito_status'] == 'ST'
    assert out[2] == {'role': 'system', 'content': 'ST', 'mid_conversation': True}
    assert len(out) == 3


def test_ensure_status_replays_stored_without_overwrite_or_duplicate():
    # B1: regenerate/continue/tool-resume: stored status replayed, not rebuilt/persisted.
    from open_webui.utils import tito

    user = {'role': 'user', 'content': 'hi', 'meta': {'tito_status': 'OLD'}}
    out, persist = tito.ensure_tito_status([user], 'NEW')
    assert persist is None
    assert out[0]['meta']['tito_status'] == 'OLD'
    assert [m['content'] for m in out if m['role'] == 'system'] == ['OLD']
    # already expanded by expand_tito_status -> no second status message
    expanded = tito.expand_tito_status([user])
    out2, persist2 = tito.ensure_tito_status(expanded, 'NEW')
    assert persist2 is None and out2 == expanded


def _fake_webhook(monkeypatch, fn):
    # The real module pulls config/env (heavy deps); tito_notify imports it lazily.
    import sys

    monkeypatch.setitem(sys.modules, 'open_webui.utils.webhook', SimpleNamespace(post_webhook=fn))


def _reset_notify():
    tito._notify_last_sent.clear()
    tito._notify_sent_times.clear()


def test_tito_notify_logs_no_webhook_url(monkeypatch, caplog):
    # N3: failure log must not contain the webhook URL.
    import logging

    _reset_notify()
    secret = 'https://discord.com/api/webhooks/123/SECRETTOKEN'
    monkeypatch.setenv('TITO_DISCORD_WEBHOOK', secret)

    async def boom(*a, **k):
        raise RuntimeError(f'failed posting to {secret}')

    _fake_webhook(monkeypatch, boom)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(tito.tito_notify('x'))
    assert 'SECRETTOKEN' not in caplog.text
    assert 'RuntimeError' in caplog.text


def test_tito_notify_drops_identical_message_within_window(monkeypatch):
    _reset_notify()
    monkeypatch.setenv('TITO_DISCORD_WEBHOOK', 'https://discord.com/api/webhooks/1/T')
    sent = []

    async def ok(name, url, message, data, *a, **k):
        sent.append(message)
        return True

    _fake_webhook(monkeypatch, ok)
    asyncio.run(tito.tito_notify('a'))
    asyncio.run(tito.tito_notify('a'))
    asyncio.run(tito.tito_notify('b'))
    assert sent == ['a', 'b']


def test_tito_notify_hourly_cap():
    _reset_notify()
    assert all(tito.notify_rate_ok(f'm{i}', now=100.0) for i in range(tito.NOTIFY_MAX_PER_HOUR))
    assert tito.notify_rate_ok('extra', now=101.0) is False
    assert tito.notify_rate_ok('extra', now=100.0 + 3600) is True  # window rolled


# --- TASK A: last-chat gap in the hidden status ------------------------------


def test_build_tito_status_adds_last_chat_line_before_closing_tag():
    # SOURCE: brief TASK A — a non-None last_chat_gap_hours adds `last chat: <N>h ago`
    # right before '</context>'; integer hours, floor, 0 allowed.
    s = tito.build_tito_status({'CURRENT_DATETIME': '2026-11-09', 'USER_LOCATION': 'Fresno'}, last_chat_gap_hours=3)
    assert s == '<context>\ntime: 2026-11-09\nlocation: Fresno\nlast chat: 3h ago\n</context>'


def test_build_tito_status_last_chat_zero_hours_allowed():
    # SOURCE: brief TASK A — 0 is a valid floor (gap under one hour).
    s = tito.build_tito_status({}, last_chat_gap_hours=0)
    assert s == '<context>\nlast chat: 0h ago\n</context>'


def test_build_tito_status_last_chat_absent_when_none():
    # SOURCE: brief TASK A — output stays byte-identical to the pre-gap build when None.
    s = tito.build_tito_status({'CURRENT_DATETIME': 'd'}, last_chat_gap_hours=None)
    assert 'last_chat' not in s
    assert s == tito.build_tito_status({'CURRENT_DATETIME': 'd'})


def test_last_chat_gap_hours_none_when_no_candidates():
    # SOURCE: brief TASK A — no previous activity at all -> None.
    assert tito.last_chat_gap_hours(1000000, [None, 0, None]) is None
    assert tito.last_chat_gap_hours(1000000, []) is None


def test_last_chat_gap_hours_ignores_none_and_zero_uses_max():
    # SOURCE: brief TASK A — ignores None/0, uses max of the rest.
    # now=7200; candidates 0, None, 3600 -> max 3600 -> gap 3600 -> 1 hour.
    assert tito.last_chat_gap_hours(7200, [0, None, 3600]) == 1


def test_last_chat_gap_hours_floors_to_hours():
    # SOURCE: brief TASK A — floors to integer hours.
    # gap = 7199 seconds -> floor 1 hour.
    assert tito.last_chat_gap_hours(7200, [1]) == 1


def test_last_chat_gap_hours_never_negative():
    # SOURCE: brief TASK A — clock skew (candidate in the future) clamps to 0.
    assert tito.last_chat_gap_hours(7200, [100000]) == 0


def test_tito_model_tool_ids_from_model_info_meta():
    from open_webui.utils.tito import tito_model_tool_ids

    model = {'id': 'tito', 'info': {'meta': {'toolIds': ['ping_tony']}}}
    assert tito_model_tool_ids(model) == ['ping_tony']
    assert tito_model_tool_ids({'id': 'tito'}) == []
    assert tito_model_tool_ids(None) == []


# --- T3: computed time / season / holidays / weather -------------------------

# 2026-11-10 04:00 PST (UTC-8, DST already ended) == 12:00 UTC; a Tuesday.
NOW_PST = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    'month, expected',
    [
        (1, 'mùa đông'),
        (2, 'mùa đông'),
        (3, 'mùa xuân'),
        (5, 'mùa xuân'),
        (6, 'mùa hạ'),
        (8, 'mùa hạ'),
        (9, 'mùa thu'),
        (11, 'mùa thu'),
        (12, 'mùa đông'),
    ],
)
def test_season_by_month(month, expected):
    assert tito.season_vi(month) == expected


def test_time_and_season_lines_from_now_in_fresno_time():
    lines = tito.build_time_lines(NOW_PST)
    assert lines[0] == 'time: thứ ba, 10/11/2026 04:00 (giờ Fresno)'
    assert lines[1] == 'season: mùa thu'


def test_holidays_next_two_each_country_with_countdown():
    # US: Thanksgiving 2026-11-26 (16 days), Christmas 2026-12-25 (45 days).
    # VN: Tết 2027-02-06 (88 days), Giỗ Tổ 2027-04-16 (157 days).
    lines = tito.build_time_lines(NOW_PST)
    assert lines[2] == (
        'holidays: US: Thanksgiving 26/11 (còn 16 ngày), Christmas 25/12 (còn 45 ngày); '
        'VN: Tết Nguyên Đán 06/02 (còn 88 ngày), Giỗ Tổ Hùng Vương 16/04 (còn 157 ngày)'
    )


def test_us_rule_based_holidays_2026():
    days = {name: day for day, name in tito.us_holidays(2026)}
    assert days['Memorial Day'].isoformat() == '2026-05-25'  # last Monday of May
    assert days['Labor Day'].isoformat() == '2026-09-07'  # first Monday of September
    assert days['Thanksgiving'].isoformat() == '2026-11-26'  # fourth Thursday of November


def test_build_status_variables_present_unchanged_even_with_now():
    # Variables win: the computed time line and season/holidays are not added.
    variables = {'CURRENT_DATETIME': '2026-11-09', 'CURRENT_TIMEZONE': 'America/Los_Angeles', 'USER_LOCATION': 'Fresno'}
    with_now = tito.build_tito_status(variables, now=NOW_PST)
    assert with_now == tito.build_tito_status(variables)
    assert with_now == '<context>\ntime: 2026-11-09\ntimezone: America/Los_Angeles\nlocation: Fresno\n</context>'


def test_build_status_without_variables_or_now_has_no_computed_lines():
    assert tito.build_tito_status({}) == '<context>\n</context>'


def test_build_status_computed_lines_when_variables_missing():
    s = tito.build_tito_status({}, now=NOW_PST)
    assert s.startswith('<context>\ntime: thứ ba, 10/11/2026 04:00 (giờ Fresno)\nseason: mùa thu\nholidays: US: ')
    assert s.endswith('\n</context>')


def test_weather_line_only_when_given_and_before_last_chat():
    base = tito.build_tito_status({}, now=NOW_PST, last_chat_gap_hours=3)
    assert 'weather' not in base
    s = tito.build_tito_status({}, now=NOW_PST, last_chat_gap_hours=3, weather='mưa, 14°C (thấp 10 cao 16)')
    assert s == base.replace('last chat:', 'weather Fresno: mưa, 14°C (thấp 10 cao 16)\nlast chat:')


def test_has_stored_status_detects_replay_on_newest_user_message():
    fresh = [{'role': 'user', 'content': 'hi'}]
    replay = [{'role': 'user', 'content': 'hi', 'meta': {'tito_status': '<context>\n</context>'}}]
    assert tito.has_stored_tito_status(fresh) is False
    assert tito.has_stored_tito_status(replay) is True
    assert tito.has_stored_tito_status([]) is False


def test_replay_keeps_stored_status_and_does_not_persist():
    stored = '<context>\ntime: old\n</context>'
    messages = [{'role': 'user', 'content': 'hi', 'meta': {'tito_status': stored}}]
    out, to_persist = tito.ensure_tito_status(messages, '<context>\ntime: NEW\n</context>')
    assert to_persist is None
    assert out[1]['content'] == stored


@pytest.mark.parametrize(
    'code, word',
    [
        (0, 'trời quang'),
        (2, 'có mây'),
        (3, 'có mây'),
        (45, 'sương mù'),
        (48, 'sương mù'),
        (61, 'mưa'),
        (67, 'mưa'),
        (73, 'tuyết'),
        (81, 'mưa rào'),
        (95, 'giông'),
        (99, 'giông'),
        (4, 'không rõ'),
    ],
)
def test_weather_code_to_vietnamese_word(code, word):
    assert tito_weather.weather_word(code) == word


def test_format_weather_rounds_and_formats():
    data = {
        'current': {'temperature_2m': 14.4, 'weather_code': 61},
        'daily': {'temperature_2m_max': [16.2], 'temperature_2m_min': [9.6]},
    }
    assert tito_weather.format_weather(data) == 'mưa, 14°C (thấp 10 cao 16)'


def test_weather_url_asks_celsius():
    # Tony 2026-11-11: temperature is always Celsius for the parents.
    assert 'temperature_unit=celsius' in tito_weather.WEATHER_URL
    assert 'fahrenheit' not in tito_weather.WEATHER_URL


class _FakeResp:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._body


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url):
        return self._resp


def test_fetch_weather_success_returns_text():
    body = {
        'current': {'temperature_2m': 14, 'weather_code': 61},
        'daily': {'temperature_2m_max': [16], 'temperature_2m_min': [10]},
    }
    result = asyncio.run(tito_weather.fetch_fresno_weather(lambda: _FakeSession(_FakeResp(200, body))))
    assert result == 'mưa, 14°C (thấp 10 cao 16)'


def test_fetch_weather_exception_returns_none_and_logs_without_url(caplog):
    def boom():
        raise RuntimeError('boom https://api.open-meteo.com/secret-ish')

    with caplog.at_level('WARNING'):
        result = asyncio.run(tito_weather.fetch_fresno_weather(boom))
    assert result is None
    assert re.search(r'TITO-ERR T\d{4} PST-[0-9a-f]{4} weather RuntimeError', caplog.text)
    assert 'open-meteo' not in caplog.text


def test_fetch_weather_http_error_returns_none_and_logs_status(caplog):
    with caplog.at_level('WARNING'):
        result = asyncio.run(tito_weather.fetch_fresno_weather(lambda: _FakeSession(_FakeResp(503))))
    assert result is None
    assert re.search(r'TITO-ERR T\d{4} PST-[0-9a-f]{4} weather 503', caplog.text)


def test_fetch_weather_malformed_payload_returns_none():
    result = asyncio.run(tito_weather.fetch_fresno_weather(lambda: _FakeSession(_FakeResp(200, {'x': 1}))))
    assert result is None


# --- TITO-ERR codes: places tool (standalone file) + tito_notify -------------

_PLACES_KEY = 'AIza-TEST-KEY-do-not-leak-1234'


def _load_places_tool():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / 'tito-deploy' / 'tools' / 'places.py'
    spec = importlib.util.spec_from_file_location('places_tool_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    'failure, expected_detail',
    [
        (lambda: urllib.error.HTTPError('https://places.googleapis.com/x', 500, 'boom', {}, None), '500'),
        (lambda: TimeoutError('timed out'), 'timeout'),
        (lambda: RuntimeError(f'boom {_PLACES_KEY} https://places.googleapis.com/v1'), 'RuntimeError'),
    ],
)
def test_places_failure_logs_tito_err_and_returns_code(monkeypatch, caplog, failure, expected_detail):
    places = _load_places_tool()
    monkeypatch.setenv('TITO_PLACES_API_KEY', _PLACES_KEY)

    def fake_urlopen(*args, **kwargs):
        raise failure()

    monkeypatch.setattr(places.urllib.request, 'urlopen', fake_urlopen)
    with caplog.at_level('ERROR'):
        result = asyncio.run(places.Tools().search_places('pharmacy'))

    assert re.search(rf'TITO-ERR T\d{{4}}-[0-9a-f]{{4}} places {re.escape(expected_detail)}', caplog.text)
    assert 'mã lỗi T' in result
    assert _PLACES_KEY not in caplog.text
    assert _PLACES_KEY not in result
    assert 'places.googleapis' not in caplog.text


def test_tito_notify_failure_logs_tito_err_without_webhook_url(monkeypatch, caplog):
    import sys
    import types

    secret_url = 'https://discord.com/api/webhooks/123/SECRET-TOKEN-xyz'

    async def failing_post_webhook(*args, **kwargs):
        raise RuntimeError(f'post failed for {secret_url}')

    fake_webhook = types.ModuleType('open_webui.utils.webhook')
    fake_webhook.post_webhook = failing_post_webhook
    monkeypatch.setitem(sys.modules, 'open_webui.utils.webhook', fake_webhook)
    monkeypatch.setenv('TITO_DISCORD_WEBHOOK', secret_url)

    with caplog.at_level('DEBUG'):
        asyncio.run(tito.tito_notify('unique-notify-message-for-tito-err-test'))

    assert re.search(r'TITO-ERR T\d{4}-[0-9a-f]{4} discord_notify RuntimeError post failed for <url>', caplog.text)
    assert 'SECRET-TOKEN' not in caplog.text
    assert 'discord.com' not in caplog.text


# --- INTERJECT: hidden next-turn admin note + chat refreeze -----------------

from open_webui.utils import tito_interject  # noqa: E402


def test_interject_add_then_pop_returns_oldest_first_and_removes(tmp_path):
    p = str(tmp_path / 'i.json')
    tito_interject.add_note('u1', '  first  ', now=1000.0, path=p)
    tito_interject.add_note('u1', 'second', now=1001.0, path=p)
    assert tito_interject.pop_notes('u1', now=1002.0, path=p) == ['first', 'second']
    assert tito_interject.pop_notes('u1', now=1002.0, path=p) == []


def test_interject_pop_is_per_user(tmp_path):
    p = str(tmp_path / 'i.json')
    tito_interject.add_note('u1', 'for one', now=1000.0, path=p)
    tito_interject.add_note('u2', 'for two', now=1000.0, path=p)
    assert tito_interject.pop_notes('u2', now=1001.0, path=p) == ['for two']
    assert tito_interject.pop_notes('u1', now=1001.0, path=p) == ['for one']


def test_interject_rejects_empty_and_too_long(tmp_path):
    p = str(tmp_path / 'i.json')
    with pytest.raises(ValueError):
        tito_interject.add_note('u1', '   ', now=1.0, path=p)
    with pytest.raises(ValueError):
        tito_interject.add_note('u1', 'x' * 1001, now=1.0, path=p)
    assert tito_interject.add_note('u1', 'x' * 1000, now=1.0, path=p) == ['x' * 1000]


def test_interject_expiry_after_24h(tmp_path):
    p = str(tmp_path / 'i.json')
    tito_interject.add_note('u1', 'old', now=0.0, path=p)
    tito_interject.add_note('u1', 'fresh', now=tito_interject.NOTE_TTL_SECONDS - 10, path=p)
    now = tito_interject.NOTE_TTL_SECONDS + 1
    assert tito_interject.pending(path=p, now=now) == {
        'u1': [{'text': 'fresh', 'ts': float(tito_interject.NOTE_TTL_SECONDS - 10)}]
    }
    assert tito_interject.pop_notes('u1', now=now, path=p) == ['fresh']


def test_interject_max_fifty_drops_oldest(tmp_path):
    p = str(tmp_path / 'i.json')
    for i in range(52):
        tito_interject.add_note('u1', f'n{i}', now=100.0 + i, path=p)
    assert tito_interject.pop_notes('u1', now=200.0, path=p) == [f'n{i}' for i in range(2, 52)]


def test_interject_clear_returns_count(tmp_path):
    p = str(tmp_path / 'i.json')
    tito_interject.add_note('u1', 'a', now=1.0, path=p)
    tito_interject.add_note('u1', 'b', now=1.0, path=p)
    assert tito_interject.clear('u1', path=p) == 2
    assert tito_interject.clear('u1', path=p) == 0
    assert tito_interject.pop_notes('u1', now=2.0, path=p) == []


def test_interject_corrupt_file_pop_returns_empty_without_raising(tmp_path, caplog):
    p = tmp_path / 'i.json'
    p.write_text('{not json', encoding='utf-8')
    with caplog.at_level('WARNING'):
        assert tito_interject.pop_notes('u1', now=1.0, path=str(p)) == []
    assert 'interject' in caplog.text


def test_interject_non_object_json_is_empty(tmp_path):
    p = tmp_path / 'i.json'
    p.write_text('["x"]', encoding='utf-8')
    assert tito_interject.pending(path=str(p), now=1.0) == {}
    assert tito_interject.pop_notes('u1', now=1.0, path=str(p)) == []


def test_interject_format_notes():
    assert tito_interject.format_notes([]) == ''
    assert tito_interject.format_notes(['gọi lại', 'nhớ uống thuốc']) == (
        'Tùng dặn (nói lại tự nhiên trong câu trả lời, một lần thôi): gọi lại\n'
        'Tùng dặn (nói lại tự nhiên trong câu trả lời, một lần thôi): nhớ uống thuốc'
    )


def test_interject_match_user_accent_and_case_insensitive():
    users = [('id-1', 'Đính'), ('id-2', 'Ngân'), ('id-3', 'Tùng')]
    assert tito_interject.match_user(users, 'dinh') == ('id-1', 'Đính')
    assert tito_interject.match_user(users, 'NGAN') == ('id-2', 'Ngân')
    assert tito_interject.match_user(users, 'id-3') == ('id-3', 'Tùng')
    assert tito_interject.match_user(users, 'nobody') is None
    assert tito_interject.match_user(users, '') is None


def test_interject_match_user_ambiguous_is_none():
    users = [('a', 'Ngân'), ('b', 'Ngan')]
    assert tito_interject.match_user(users, 'ngan') is None
    assert tito_interject.match_user([('a', 'Hoàng Ngân'), ('b', 'Ngân Nguyễn')], 'ngan') is None
    assert tito_interject.match_user([('a', 'Hoàng Ngân'), ('b', 'Minh')], 'ngan') == ('a', 'Hoàng Ngân')


def test_drop_frozen_system_removes_only_that_key():
    meta = {'tito_system': {'block1': 'a', 'block2': 'b', 'sha256': 'x'}, 'tags': ['t'], 'other': 1}
    new_meta, had = tito.drop_frozen_system(meta)
    assert had is True
    assert new_meta == {'tags': ['t'], 'other': 1}
    assert 'tito_system' in meta  # input not mutated


def test_drop_frozen_system_absent_or_empty():
    assert tito.drop_frozen_system({'tags': []}) == ({'tags': []}, False)
    assert tito.drop_frozen_system({}) == ({}, False)
    assert tito.drop_frozen_system(None) == ({}, False)
