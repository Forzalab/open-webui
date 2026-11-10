"""Red test for O2: ``upsert_message_to_history`` preserves ``meta.tito_status``.

Fails today: the preserved-meta key list in ``ChatTable.upsert_message_to_history``
(backend/open_webui/models/chats.py:1155-1171) does not include ``tito_status``, so a
re-upsert whose incoming meta carries any non-preserved key drops it.
"""

from open_webui.models.chats import ChatTable


def test_upsert_message_to_history_preserves_tito_status():
    # SOURCE: Orc O2 — add "tito_status" to the preserved meta keys in
    # upsert_message_to_history (chats.py:1155-1171), like the existing
    # voice/task_id/response_started_at/response_ended_at keys (chats.py:1158,1166).
    history = {'messages': {'m1': {'id': 'm1', 'role': 'user', 'content': 'chào', 'meta': {'tito_status': 'S'}}}}
    # Re-upsert the same message with meta that does NOT include tito_status and
    # carries a non-preserved key -> exercises the else branch (chats.py:1160-1171).
    updated = ChatTable.upsert_message_to_history(
        history,
        'm1',
        {'role': 'user', 'content': 'chào edited', 'meta': {'some_other': 'y'}},
    )
    assert updated['meta']['tito_status'] == 'S'
    assert updated['meta']['some_other'] == 'y'
