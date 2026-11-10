"""Red tests for ``open_webui.utils.tito`` (PATCH A / C / G / B5 pure helpers).

These tests FAIL today because ``open_webui.utils.tito`` does not exist yet
(module-level import -> ImportError). They pass only when the module exposes the
exact contract in ``tito-spec/SPEC.md``.

Every expected value names its SOURCE: an existing file:line when one exists,
otherwise the locked plan / vet document / Orc decision that defines the value.
No value is "because the spec says".
"""

import hashlib
from types import SimpleNamespace

from open_webui.utils import tito

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


def test_tito_notify_logs_no_webhook_url(monkeypatch, caplog):
    # N3: failure log must not contain the webhook URL.
    import asyncio
    import logging

    pytest = __import__('pytest')
    try:
        from open_webui.utils import middleware
    except Exception as e:  # heavy import; skip if env lacks deps
        pytest.skip(f'middleware not importable: {e}')

    secret = 'https://discord.com/api/webhooks/123/SECRETTOKEN'
    monkeypatch.setenv('TITO_DISCORD_WEBHOOK', secret)

    async def boom(*a, **k):
        raise RuntimeError(f'failed posting to {secret}')

    monkeypatch.setattr(middleware, 'post_webhook', boom)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(middleware._tito_notify('x'))
    assert 'SECRETTOKEN' not in caplog.text


# --- TASK A: last-chat gap in the hidden status ------------------------------


def test_build_tito_status_adds_last_chat_line_before_closing_tag():
    # SOURCE: brief TASK A — a non-None last_chat_gap_hours adds `last_chat: <N>h ago`
    # right before '</context>'; integer hours, floor, 0 allowed.
    s = tito.build_tito_status({'CURRENT_DATETIME': '2026-11-09', 'USER_LOCATION': 'Fresno'}, last_chat_gap_hours=3)
    assert s == '<context>\ntime: 2026-11-09\nlocation: Fresno\nlast_chat: 3h ago\n</context>'


def test_build_tito_status_last_chat_zero_hours_allowed():
    # SOURCE: brief TASK A — 0 is a valid floor (gap under one hour).
    s = tito.build_tito_status({}, last_chat_gap_hours=0)
    assert s == '<context>\nlast_chat: 0h ago\n</context>'


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
