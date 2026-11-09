# KEY.md — answers / expected values (rev 2)

- **Model gate id:** `'tito'` (exact). OWUI: `model['id']` (used at mw:2192). Pipe:
  `__metadata__['model']['id']` (main.py:1343) — VERIFY-AT-RUNTIME (C2).
- **Raw prompt source:** `model_info.params.system` from `Models.get_model_by_id` in
  main.py (main.py:1160); NOT `model['info']['params']['system']` (redacted by
  `public_model_params`, utils/models.py:36-57). Templated path today: functions.py:275.
- **Two blocks (O7):** `block1` = raw prompt; `block2` = `SNAPSHOT_HEADING + '\n' +
  snapshot`. Combined for the messages list = `block1 + '\n\n' + block2`.
- **meta shape:** `chat.meta['tito_system'] = {'block1': str, 'block2': str,
  'sha256': sha256_hex(block1 + '\n\n' + block2)}`.
- **SNAPSHOT_HEADING:** `'NHỮNG ĐIỀU TITO NHỚ VỀ ÔNG'`.
- **NO_MEMORIES_SENTINEL:** `'(chưa có ký ức nào)'`. **MEMORY_UNAVAILABLE_SENTINEL:**
  `'(memory unavailable this chat)'` (exact, vet M6).
- **Snapshot sort key:** `(path or '', content or '', id or '')`. No type filter, no
  timestamps. Line format: `- {path}: {content}` if path else `- {content}`.
- **mid_conversation marker (C1):** TOP-LEVEL key `mid_conversation` (bool). Status text
  stored at `user_msg['meta']['tito_status']`.
- **Status builder (O4):** `build_tito_status(variables, budget_counters=None)` →
  `<context>\ntime: {CURRENT_DATETIME}\ntimezone: {CURRENT_TIMEZONE}\nlocation:
  {USER_LOCATION}\n</context>`; each line omitted when its variable is missing/empty.
  `budget_counters` = hook arg, empty for now.
- **features forced (B3):** `{'memory': True}`.
- **background_tasks (O5):** wholesale `{'title_generation': True}`.
- **params.max_tokens (O5):** `16000`. **stream_options.include_usage (O5):** `True`.
- **use_builtin_tools (B2):** `is_note_chat or is_tito or (existing condition)`.
- **TITO_TEMP_CHAT_ERROR:** `'Tito chỉ dùng được trong cuộc trò chuyện đã lưu. Ông mở cuộc
  trò chuyện mới nhé.'` **TITO_NO_CHAT_ERROR:** `'Cuộc trò chuyện này không tìm thấy. Ông
  mở cuộc trò chuyện mới nhé.'` (GUESS — Vietnamese wording not specified by the Orc.)
- **Expected memory tool names (O6):** `search_memories, list_memory_paths,
  read_memory_path, list_memories, update_memory, add_memory, replace_memory_content,
  delete_memory` (tools.py:816-827).
- **Expected file tool names (O6):** `list_chat_files, query_chat_files, grep_chat_files,
  view_file, display_file` (tools.py:750).
- **O6 model checks:** `capabilities.memory` != False, `capabilities.file_upload` != False,
  `builtinTools.memory` != False (defaults True, tools.py:647-648, 653).
- **O8 config checklist (must all be False):** `ENABLE_PERSISTENT_CONFIG`,
  `RAG_SYSTEM_CONTEXT`, `memories.system_context.enable`.
- **TITO_TOOLS_FILE (C3):** JSON list in ANTHROPIC tools format
  `[{name, description, input_schema}, …]` exactly as sent to the API; includes file +
  memory + calendar + TinyFish tools; written by a dump helper in the B5 self-check.
- **Envs:** `TITO_SELFCHECK_USER_ID` (non-admin user id/email), `TITO_DISCORD_WEBHOOK`.
- **Non-admin permissions (config):** `features.memories`, `chat.file_upload`
  (tools.py:814, 748). Block temporary chats for Dad via `chat.temporary` off.
