"""Red tests for ``open_webui.utils.tito`` (PATCH A / C / G / B5 pure helpers).

These tests FAIL today because ``open_webui.utils.tito`` does not exist yet
(module-level import -> ImportError). They pass only when the module exposes the
exact contract in ``tito-spec/SPEC.md``.

Every expected value names its SOURCE: an existing file:line when one exists,
otherwise the locked plan / vet document that defines the value. No value is
"because the spec says".
"""
import hashlib
from types import SimpleNamespace

from open_webui.utils import tito

# --- PATCH G: model gating -------------------------------------------------

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


def test_lock_background_tasks_strips_follow_up_and_tags_keeps_title():
    # SOURCE: brief PATCH G — "follow_up/tags background tasks off (title on)".
    # Task keys are TASKS enum (backend/open_webui/constants.py:143-145):
    #   title_generation / follow_up_generation / tags_generation.
    tasks = {
        'title_generation': True,
        'follow_up_generation': True,
        'tags_generation': True,
    }
    locked = tito.lock_background_tasks(dict(tasks))
    assert locked == {'title_generation': True}


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
    # sorted by (path or '', content or '', id or ''): no-path rows first ('' < any
    # path), then by content code point ('mua...' < 'thích...' since 'm' < 't'),
    # then the path row last. No timestamps anywhere.
    assert lines[0] == '- mua xăng ở Fresno'          # no path, content 'm...'
    assert lines[1] == '- thích Tuấn Ngọc'           # no path, content 't...'
    assert lines[2] == '- sức khỏe: bảo hiểm 35 đô'  # has path -> sorts last
    # invariant: no timestamps leak into the snapshot
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
    snapshot = tito.build_memory_snapshot(memories)
    assert snapshot == '- ok'


# --- PATCH A: frozen system (block1 + block2) ------------------------------

def test_build_tito_system_raw_prompt_untemplated():
    # SOURCE: brief PATCH A — "block1 raw Tito prompt ... no {{ }} templating".
    raw = 'Bạn là Tito. Hãy hỏi {{USER_NAME}}?'  # literal braces must stay verbatim
    system = tito.build_tito_system(raw, [SimpleNamespace(id='a', path=None, content='x')])
    assert system.startswith(raw + '\n\n')
    assert '{{USER_NAME}}' in system  # no substitution happened


def test_build_tito_system_contains_heading_and_snapshot():
    # SOURCE: heading string mandated by vet M5 (must NOT contain the volatile
    # markers the pipe strips: `<memory_context>` — memory.py:17-18 — nor
    # `User Context:`); snapshot content follows the heading.
    raw = 'Tito prompt'
    system = tito.build_tito_system(raw, [SimpleNamespace(id='a', path=None, content='mem')])
    assert tito.SNAPSHOT_HEADING in system
    assert '- mem' in system
    # M5: heading must avoid the pipe's volatile markers.
    assert '<memory_context>' not in tito.SNAPSHOT_HEADING
    assert 'User Context:' not in tito.SNAPSHOT_HEADING


def test_build_tito_system_unavailable_uses_unavailable_sentinel():
    # SOURCE: vet M6 — on exception write "(memory unavailable this chat)".
    raw = 'Tito prompt'
    system = tito.build_tito_system_unavailable(raw)
    assert tito.MEMORY_UNAVAILABLE_SENTINEL in system
    assert system.startswith(raw)


def test_freeze_and_get_frozen_system_roundtrip_with_sha256():
    # SOURCE: DECISIONS — "meta.tito_system (+ sha256)".
    system = 'prompt\n\nmemory'
    meta = tito.freeze_tito_system({}, system)
    assert meta['tito_system']['system'] == system
    assert meta['tito_system']['sha256'] == hashlib.sha256(system.encode()).hexdigest()
    assert tito.get_frozen_tito_system(meta) == system


def test_get_frozen_tito_system_returns_none_when_absent():
    # SOURCE: DECISIONS — freeze only on the FIRST request; absent = first turn.
    assert tito.get_frozen_tito_system({}) is None


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
    # mid_conversation status survives, in place (after its user msg)
    assert {'role': 'system', 'content': 'status', 'mid_conversation': True} in out
    # Conduit's index-0 system is gone
    assert not any(m.get('content') == 'conduit index-0 system' for m in out)


# --- PATCH C: status in user message meta ----------------------------------

def test_build_tito_status_message_is_marked_mid_conversation():
    # SOURCE: brief PATCH C — "msgs marked mid_conversation pass through in place";
    # marker key convention is `mid_conversation` (LOCKED plan LCR section).
    msg = tito.build_tito_status_message('time/location')
    assert msg['role'] == 'system'
    assert msg['content'] == 'time/location'
    assert msg['mid_conversation'] is True


def test_store_tito_status_writes_user_meta():
    # SOURCE: vet H2 — "Store the exact status string in the USER message's meta
    # (e.g. meta.tito_status)"; meta survives replay via MESSAGE_REPLAY_KEYS
    # (backend/open_webui/utils/middleware.py:1857).
    user_msg = {'role': 'user', 'content': 'chào', 'meta': {}}
    out = tito.store_tito_status(user_msg, 'status text')
    assert out['meta']['tito_status'] == 'status text'


def test_expand_tito_status_inserts_system_after_user_message():
    # SOURCE: brief PATCH C — status is persisted in user msg meta and expanded
    # into a mid_conversation system message right after that user message.
    messages = [
        {'role': 'system', 'content': 'frozen'},
        {'role': 'user', 'content': 'chào', 'meta': {'tito_status': 'S'}},
        {'role': 'assistant', 'content': 'hi'},
    ]
    out = tito.expand_tito_status(messages)
    # user msg (idx1) is followed by the mid_conversation status (idx2)
    assert out[1]['role'] == 'user'
    assert out[2] == {'role': 'system', 'content': 'S', 'mid_conversation': True}
    assert out[3]['role'] == 'assistant'


def test_expand_tito_status_noop_without_status_meta():
    # SOURCE: brief PATCH C — expansion only applies to user msgs that carry a status.
    messages = [
        {'role': 'user', 'content': 'chào'},
        {'role': 'assistant', 'content': 'hi'},
    ]
    assert tito.expand_tito_status(messages) == messages
