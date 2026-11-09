"""Red tests for PATCH C: ``merge_system_messages`` (backend/open_webui/utils/misc.py).

Current behavior (misc.py:727-751) merges EVERY role:system message into one at
position 0. PATCH C changes it to merge only the LEADING run and pass
mid_conversation-marked system messages through in place. These tests FAIL today
on the mid_conversation case (they get collapsed to position 0) and on the
backward-compat case when content extraction differs.
"""
from open_webui.utils.misc import merge_system_messages


def test_merges_leading_run_only_keeps_mid_conversation_in_place():
    # SOURCE: brief PATCH C — "merges only the LEADING run of system msgs;
    # msgs marked mid_conversation pass through in place".
    messages = [
        {'role': 'system', 'content': 'block A'},
        {'role': 'system', 'content': 'block B'},
        {'role': 'user', 'content': 'chào'},
        {'role': 'system', 'content': 'status 1', 'mid_conversation': True},
        {'role': 'assistant', 'content': 'hi'},
        {'role': 'user', 'content': 'tiếp'},
        {'role': 'system', 'content': 'status 2', 'mid_conversation': True},
    ]
    out = merge_system_messages(messages)
    assert out[0] == {'role': 'system', 'content': 'block A\nblock B'}
    assert out[1]['role'] == 'user'
    # mid_conversation status messages stay AFTER their user messages, unchanged.
    assert {'role': 'system', 'content': 'status 1', 'mid_conversation': True} in out
    assert {'role': 'system', 'content': 'status 2', 'mid_conversation': True} in out
    # they are NOT merged into position 0
    assert 'status 1' not in out[0]['content'] and 'status 2' not in out[0]['content']


def test_backward_compatible_without_mid_conversation_marker():
    # SOURCE: brief "other models unchanged" — messages without the marker must
    # merge exactly as the old code did (all system content joined at index 0).
    messages = [
        {'role': 'system', 'content': 'A'},
        {'role': 'user', 'content': 'x'},
        {'role': 'assistant', 'content': 'y'},
    ]
    out = merge_system_messages(messages)
    assert out[0] == {'role': 'system', 'content': 'A'}
    assert [m['role'] for m in out] == ['system', 'user', 'assistant']


def test_no_leading_system_returns_messages_unchanged():
    # SOURCE: brief PATCH C — with no leading system run, nothing to merge;
    # mid_conversation messages must NOT be dropped (old code dropped all system).
    messages = [
        {'role': 'user', 'content': 'chào'},
        {'role': 'system', 'content': 'status', 'mid_conversation': True},
        {'role': 'assistant', 'content': 'hi'},
    ]
    out = merge_system_messages(messages)
    assert out == messages


def test_mid_conversation_system_at_front_is_not_merged_into_leading_run():
    # SOURCE: brief PATCH C — a mid_conversation marker stops the leading run.
    messages = [
        {'role': 'system', 'content': 'status', 'mid_conversation': True},
        {'role': 'system', 'content': 'real system'},
        {'role': 'user', 'content': 'x'},
    ]
    out = merge_system_messages(messages)
    # leading run is empty (first msg is mid_conversation) -> unchanged order
    assert out[0] == {'role': 'system', 'content': 'status', 'mid_conversation': True}
    assert out[1] == {'role': 'system', 'content': 'real system'}
