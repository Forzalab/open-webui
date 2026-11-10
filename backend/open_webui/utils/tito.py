"""Pure helpers for the Tito model (frozen per-chat system, status, self-check).

This module deliberately imports only the stdlib (``hashlib``) and the light
``open_webui.utils.chat_id`` module (uuid-only).  It must stay free of any DB,
config, or env imports so its functions remain unit-testable without a live app.
"""

from __future__ import annotations

import hashlib

from open_webui.utils.chat_id import is_temporary_chat_id

TITO_MODEL_ID = 'tito'
SNAPSHOT_HEADING = 'NHỮNG ĐIỀU TITO NHỚ VỀ ÔNG'
NO_MEMORIES_SENTINEL = '(chưa có ký ức nào)'
MEMORY_UNAVAILABLE_SENTINEL = '(memory unavailable this chat)'
TITO_MAX_TOKENS = 16000

# Orc O3 — Vietnamese error strings (exact text lives in KEY.md, not present here).
TITO_TEMP_CHAT_ERROR = 'Tito không hỗ trợ trò chuyện tạm thời. Vui lòng tạo một cuộc trò chuyện đã lưu.'
TITO_NO_CHAT_ERROR = 'Không tìm thấy cuộc trò chuyện. Vui lòng tạo cuộc trò chuyện mới.'


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def is_tito_model(model: dict) -> bool:
    return bool(model) and model.get('id') == TITO_MODEL_ID


def tito_features() -> dict:
    return {'memory': True}


def lock_background_tasks(tasks: dict) -> dict:
    return {'title_generation': True}


def tito_stream_options() -> dict:
    return {'include_usage': True}


def build_memory_snapshot(memories: list) -> str:
    rows = [memory for memory in (memories or []) if (getattr(memory, 'content', None) or '').strip()]
    if not rows:
        return NO_MEMORIES_SENTINEL

    def sort_key(memory):
        return (
            getattr(memory, 'path', None) or '',
            getattr(memory, 'content', None) or '',
            getattr(memory, 'id', None) or '',
        )

    lines = []
    for memory in sorted(rows, key=sort_key):
        path = getattr(memory, 'path', None)
        content = getattr(memory, 'content', None)
        lines.append(f'- {path}: {content}' if path else f'- {content}')
    return '\n'.join(lines)


def build_tito_blocks(prompt_raw: str | None, memories: list) -> tuple[str, str]:
    block1 = prompt_raw or ''
    block2 = f'{SNAPSHOT_HEADING}\n{build_memory_snapshot(memories)}'
    return block1, block2


def build_tito_blocks_unavailable(prompt_raw: str | None) -> tuple[str, str]:
    block1 = prompt_raw or ''
    block2 = f'{SNAPSHOT_HEADING}\n{MEMORY_UNAVAILABLE_SENTINEL}'
    return block1, block2


def freeze_tito_system(meta: dict, block1: str, block2: str) -> dict:
    meta = dict(meta or {})
    meta['tito_system'] = {
        'block1': block1,
        'block2': block2,
        'sha256': sha256_hex(join_tito_system(block1, block2)),
    }
    return meta


def join_tito_system(block1: str, block2: str) -> str:
    """Single frozen system string; the pipe splits it on the first ``\\n\\n`` + SNAPSHOT_HEADING."""
    return f'{block1}\n\n{block2}'


def get_frozen_tito_system(meta: dict) -> str | None:
    blocks = get_frozen_tito_blocks(meta)
    if blocks is None:
        return None
    return join_tito_system(*blocks)


def get_frozen_tito_blocks(meta: dict) -> tuple[str, str] | None:
    frozen = (meta or {}).get('tito_system')
    if not isinstance(frozen, dict):
        return None
    block1 = frozen.get('block1')
    block2 = frozen.get('block2')
    if block1 is None or block2 is None:
        return None
    return block1, block2


def apply_frozen_system(messages: list[dict], frozen_system: str) -> list[dict]:
    kept = [
        message for message in messages if not (message.get('role') == 'system' and not message.get('mid_conversation'))
    ]
    return [{'role': 'system', 'content': frozen_system}, *kept]


def last_chat_gap_hours(now_epoch: int, candidates: list[int | None]) -> int | None:
    """Floor the elapsed hours since the newest candidate, or ``None`` with no candidate.

    Ignores ``None`` and ``0`` entries (no prior activity), takes the ``max`` of the
    rest, floors to whole hours, and never returns a negative value.
    """
    valid = [c for c in (candidates or []) if isinstance(c, int) and c > 0]
    if not valid:
        return None
    gap = max(0, int(now_epoch) - max(valid))
    return gap // 3600


def build_tito_status(variables: dict, budget_counters=None, last_chat_gap_hours=None) -> str:
    variables = variables or {}
    lines = ['<context>']
    if variables.get('CURRENT_DATETIME'):
        lines.append(f'time: {variables["CURRENT_DATETIME"]}')
    if variables.get('CURRENT_TIMEZONE'):
        lines.append(f'timezone: {variables["CURRENT_TIMEZONE"]}')
    if variables.get('USER_LOCATION'):
        lines.append(f'location: {variables["USER_LOCATION"]}')
    if last_chat_gap_hours is not None:
        lines.append(f'last_chat: {last_chat_gap_hours}h ago')
    lines.append('</context>')
    return '\n'.join(lines)


def build_tito_status_message(status_text: str) -> dict:
    return {'role': 'system', 'content': status_text, 'mid_conversation': True}


def store_tito_status(message: dict, status_text: str) -> dict:
    meta = dict(message.get('meta') or {})
    meta['tito_status'] = status_text
    return {**message, 'meta': meta}


def expand_tito_status(messages: list[dict]) -> list[dict]:
    out = []
    for message in messages:
        out.append(message)
        if message.get('role') == 'user':
            status = (message.get('meta') or {}).get('tito_status')
            if status:
                out.append(build_tito_status_message(status))
    return out


def ensure_tito_status(messages: list[dict], status_text: str) -> tuple[list[dict], str | None]:
    """Attach the status to the newest user message, exactly once.

    Returns ``(messages, to_persist)``.  If the newest user message already carries
    ``meta.tito_status`` (regenerate / continue / tool-resume) the stored status is
    replayed (a status message is inserted only if ``expand_tito_status`` has not
    already done so) and ``to_persist`` is ``None``; the stored value is never
    overwritten.  Otherwise the new status is stored on the message and inserted,
    and ``to_persist`` is the text to write to the DB.
    """
    messages = list(messages)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get('role') != 'user':
            continue
        stored = (messages[i].get('meta') or {}).get('tito_status')
        if stored:
            nxt = messages[i + 1] if i + 1 < len(messages) else None
            if not (nxt and nxt.get('role') == 'system' and nxt.get('mid_conversation')):
                messages.insert(i + 1, build_tito_status_message(stored))
            return messages, None
        messages[i] = store_tito_status(messages[i], status_text)
        messages.insert(i + 1, build_tito_status_message(status_text))
        return messages, status_text
    return messages, None


def tito_chat_error(chat, chat_id: str, is_new_chat: bool = False) -> str | None:
    if is_temporary_chat_id(chat_id):
        return TITO_TEMP_CHAT_ERROR
    if chat is None and not is_new_chat:
        return TITO_NO_CHAT_ERROR
    return None


def tito_memory_tool_names() -> list[str]:
    return [
        'search_memories',
        'list_memory_paths',
        'read_memory_path',
        'list_memories',
        'update_memory',
        'add_memory',
        'replace_memory_content',
        'delete_memory',
    ]


def tito_file_tool_names() -> list[str]:
    return [
        'list_chat_files',
        'query_chat_files',
        'grep_chat_files',
        'view_file',
        'display_file',
    ]


def tito_required_tool_names() -> list[str]:
    return tito_memory_tool_names() + tito_file_tool_names()


def tito_missing_tools(present_names) -> list[str]:
    present = set(present_names or [])
    return [name for name in tito_required_tool_names() if name not in present]


def tito_model_checks(model: dict) -> list[str]:
    model = model or {}
    capabilities = model.get('info', {}).get('meta', {}).get('capabilities') or {}
    builtin_tools = model.get('info', {}).get('meta', {}).get('builtinTools') or {}
    fails = []
    if capabilities.get('memory') is False:
        fails.append('capabilities.memory disabled')
    if capabilities.get('file_upload') is False:
        fails.append('capabilities.file_upload disabled')
    if builtin_tools.get('memory') is False:
        fails.append('builtinTools.memory disabled')
    return fails


def tito_config_checks(config_values: dict) -> list[str]:
    config_values = config_values or {}
    fails = []
    for key in ('ENABLE_PERSISTENT_CONFIG', 'RAG_SYSTEM_CONTEXT', 'memories.system_context.enable'):
        if config_values.get(key):
            fails.append(f'{key} must be disabled')
    return fails
