# KEY.md — answers / expected values (PRO answers; coder does NOT edit)

- **Model gate id:** `'tito'` (exact). Model dict id field used at mw:2192.
- **Raw prompt source:** `model_info.params.system` from `Models.get_model_by_id` in
  main.py (loaded at main.py:1160). NOT `model['info']['params']['system']` — that is
  redacted by `public_model_params` (utils/models.py:36-57). Templated application today
  is functions.py:275 → `apply_system_prompt_to_body`; PATCH A bypasses it (raw only).
- **SNAPSHOT_HEADING:** `'NHỮNG ĐIỀU TITO NHỚ VỀ ÔNG'` (avoids `<memory_context>`
  memory.py:17-18 and `User Context:`).
- **NO_MEMORIES_SENTINEL:** `'(chưa có ký ức nào)'`. **MEMORY_UNAVAILABLE_SENTINEL:**
  `'(memory unavailable this chat)'` (exact, vet M6).
- **Snapshot sort key:** `(path or '', content or '', id or '')`. No type filter, no
  timestamps. Line format: `- {path}: {content}` if path else `- {content}`
  (memory_label memory.py:43-44).
- **meta shape:** `chat.meta['tito_system'] = {'system': str, 'sha256': hex}`.
- **mid_conversation marker key:** `mid_conversation` (bool). Status stored at
  `user_msg['meta']['tito_status']`.
- **features forced:** `{'memory': True}`; `web_search`/`image_generation`/
  `code_interpreter`/`voice` absent (=false).
- **background_tasks kept:** `title_generation` only; strip `follow_up_generation`,
  `tags_generation` (constants.py:143-145).
- **use_builtin_tools:** `is_note_chat or is_tito or (existing session/function_calling
  condition)`.
- **Expected memory tool names (B5):** `search_memories, list_memory_paths,
  read_memory_path, list_memories, update_memory, add_memory, replace_memory_content,
  delete_memory` (tools.py:816-827).
- **Expected file tool names (B5):** `list_chat_files, query_chat_files,
  grep_chat_files, view_file, display_file` (tools.py:750).
- **B5 user id env:** `TITO_SELFCHECK_USER_ID` (fallback email→Users). **Webhook env:**
  `TITO_DISCORD_WEBHOOK`.
- **Non-admin permissions required (config, not code):** `features.memories`,
  `chat.file_upload` (tools.py:814, 748).
