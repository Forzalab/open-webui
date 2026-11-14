"""Per-model Tito profiles: 'tito' unchanged, 'mimi' uses its own strings. Pure functions only."""

from datetime import date
from types import SimpleNamespace

from open_webui.utils import tito


def test_profile_lookup_tito_mimi_and_other():
    assert tito.tito_profile({'id': 'tito'})['label'] == 'Tito'
    assert tito.tito_profile('mimi')['label'] == 'Mimi'
    assert tito.tito_profile({'id': 'mimi'}) is tito.TITO_PROFILES['mimi']
    assert tito.tito_profile({'id': 'claude-sonnet-5-5'}) is None
    assert tito.tito_profile(None) is None
    assert tito.tito_profile('') is None


def test_is_tito_model_true_for_mimi_false_for_other():
    assert tito.is_tito_model({'id': 'mimi'}) is True
    assert tito.is_tito_model({'id': 'tito'}) is True
    assert tito.is_tito_model({'id': 'claude-sonnet-5-5'}) is False
    assert tito.is_tito_model(None) is False


def test_tito_profile_values_match_legacy_constants():
    p = tito.TITO_PROFILES['tito']
    assert p['snapshot_heading'] == tito.SNAPSHOT_HEADING == 'NHỮNG ĐIỀU TITO NHỚ VỀ ANH'
    assert p['temp_chat_error'] == tito.TITO_TEMP_CHAT_ERROR
    assert p['no_chat_error'] == tito.TITO_NO_CHAT_ERROR


def test_mimi_block2_uses_mimi_heading():
    mem = [SimpleNamespace(id='a', path='p', content='x')]
    heading = tito.TITO_PROFILES['mimi']['snapshot_heading']
    _, block2 = tito.build_tito_blocks('raw', mem, heading=heading)
    assert heading == 'NHỮNG ĐIỀU MIMI NHỚ VỀ BẠN'
    assert block2.startswith('NHỮNG ĐIỀU MIMI NHỚ VỀ BẠN\n')
    assert 'TITO' not in block2


def test_mimi_unavailable_block2_uses_mimi_heading():
    heading = tito.TITO_PROFILES['mimi']['snapshot_heading']
    _, block2 = tito.build_tito_blocks_unavailable('raw', heading=heading)
    assert block2 == f'{heading}\n{tito.MEMORY_UNAVAILABLE_SENTINEL}'


def test_tito_block2_byte_identical_to_legacy_default():
    mem = [SimpleNamespace(id='a', path='p', content='x')]
    _, default_b2 = tito.build_tito_blocks('raw', mem)
    _, explicit_b2 = tito.build_tito_blocks('raw', mem, heading=tito.TITO_PROFILES['tito']['snapshot_heading'])
    assert default_b2 == explicit_b2 == f'NHỮNG ĐIỀU TITO NHỚ VỀ ANH\n{tito.build_memory_snapshot(mem)}'
    _, unavail = tito.build_tito_blocks_unavailable('raw')
    assert unavail == 'NHỮNG ĐIỀU TITO NHỚ VỀ ANH\n(memory unavailable this chat)'


def test_mimi_frozen_system_splits_on_mimi_heading():
    heading = tito.TITO_PROFILES['mimi']['snapshot_heading']
    b1, b2 = tito.build_tito_blocks('PROMPT\n\nparas', [], heading=heading)
    joined = tito.join_tito_system(b1, b2)
    head, sep, tail = joined.partition('\n\n' + heading)
    assert head == b1 and sep and (heading + tail) == b2


def test_mimi_chat_error_texts():
    temp = tito.tito_chat_error(None, 'temporary:abc', profile=tito.TITO_PROFILES['mimi'])
    assert temp == 'Mimi chưa hỗ trợ trò chuyện tạm thời. Bạn tạo một cuộc trò chuyện đã lưu nha.'
    missing = tito.tito_chat_error(None, 'saved-chat-id', is_new_chat=False, profile=tito.TITO_PROFILES['mimi'])
    assert missing == 'Không tìm thấy cuộc trò chuyện. Bạn tạo cuộc trò chuyện mới nha.'
    assert tito.tito_chat_error(None, 'saved-chat-id', is_new_chat=True, profile=tito.TITO_PROFILES['mimi']) is None


def test_tito_chat_error_default_profile_is_tito_text():
    assert tito.tito_chat_error(None, 'temporary:abc') == tito.TITO_TEMP_CHAT_ERROR
    assert tito.tito_chat_error(None, 'saved-chat-id') == tito.TITO_NO_CHAT_ERROR
    assert tito.tito_chat_error(None, 'temporary:abc', profile=tito.TITO_PROFILES['tito']) == tito.TITO_TEMP_CHAT_ERROR


def test_mimi_tool_ids_read_from_model_meta():
    model = {'id': 'mimi', 'info': {'meta': {'toolIds': ['memory_tool', '', 'x']}}}
    assert tito.tito_model_tool_ids(model) == ['memory_tool', 'x']
