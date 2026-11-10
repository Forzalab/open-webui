# SPEC — Tito OWUI-side patches (A, C, G, B5) — rev 2

Status: PRO spec (do NOT implement). Companion to `FLASH-BRIEF.md` (ACs for the coder)
and `KEY.md` (answers/expected values). Rev 2 folds in the reviewer's blocking errors and
the Orc's final decisions (C1-C3, O1-O8). All changes gated on **model id `"tito"`**;
every other model's request path is byte-for-byte unchanged.

## 1. Goal

Freeze Tito's per-chat system prompt and tool configuration so that every turn of a
chat replays an identical prefix (cache-stable, no 400s), independent of client-sent UI
state, Conduit's injected system message, live prompt edits, or a dead websocket. Plus a
loud startup self-check that the frozen tool list is actually attainable for a NON-admin
user.

## 2. Why

- Anthropic prompt caching keys on the message prefix; any drift rebuilds the cache and
  can mismatch preserved `thinking` blocks → 400 or silent quality drop (vet B1-B4, H1-H3).
- Dad is non-admin; Tony tests as admin, and admin bypasses permission gates
  (mw:2366 `role == 'admin' or has_permission`) — so Tony's green test proves nothing
  (vet B5).
- Conduit sends `session_id` only when a socket is alive; without it OWUI drops all
  builtin tools (mw:2070-2074) (vet B2).

## 3. Non-goals (explicitly OUT of this spec)

- Pipe patches B (fixed config dict, no nudge/terminal hint, sha256 log), D
  (status → role:system mid-conversation message + beta header + cache breakpoint), the
  budget gate. Those live in the Podden pipe fork, not `backend/open_webui/`.
  (C3's frozen-tools file is WRITTEN here by a dump helper, consumed by the pipe.)
- The memory-as-file variant (rejected; DECISIONS Q18 keeps snapshot as system block 2).
- Mid-chat Haiku swap (CUT), keepalive (CUT), "still here" gesture (CUT).

## 4. Verified file:line map (docs → real code)

`mw` = `backend/open_webui/utils/middleware.py`, `misc` = `backend/open_webui/utils/misc.py`,
`tools` = `backend/open_webui/utils/tools.py`, `chats` = `backend/open_webui/models/chats.py`,
`memories` = `backend/open_webui/models/memories.py`. ✓ = exact; Δ = doc line off, real used.

| Doc claim                                                   | Real location                  | Status |
| ----------------------------------------------------------- | ------------------------------ | ------ |
| `use_builtin_tools` mw:2069-2073                            | mw:2070-2074                   | Δ (+1) |
| `chat = get_chat_by_id` mw:2068                             | mw:2068                        | ✓      |
| `load_messages_from_db` drops empty assistant mw:1879-1883  | fn mw:1860, filter mw:1882     | Δ      |
| re-attach system after DB load mw:2110-2111                 | mw:2113-2114                   | Δ      |
| `apply_system_prompt_to_body` replace mw:2205               | mw:2205-2212                   | ✓      |
| `variables = pop` mw:2322                                   | mw:2322                        | ✓      |
| `features = pop` mw:2345                                    | mw:2345                        | ✓      |
| memory permission check (admin bypass) mw:2366              | mw:2366                        | ✓      |
| `tool_ids = pop` mw:2426                                    | mw:2426                        | ✓      |
| `skill_ids` mw:2482-2483                                    | mw:2482-2483                   | ✓      |
| MCP `instructions` into system mw:2691                      | mw:2690-2695                   | ✓      |
| MCP connect failure `log.exception + continue` mw:2725-2740 | mw:2725-2739                   | Δ      |
| terminal system prompt mw:2779                              | mw:2779                        | ✓      |
| tool-server system prompt mw:2796                           | mw:2796                        | ✓      |
| builtin tools injection mw:2826-2829                        | mw:2828-2872 (call mw:2854)    | ✓      |
| `is_file_context_enabled` mw:2926-2932                      | fn tools:588-593, call mw:2926 | Δ      |
| `normalize_messages_for_model` → `merge_system_messages`    | mw:233-236, call mw:3007       | ✓      |
| `merge_system_messages` misc:727                            | misc:727-751                   | ✓      |
| `add_or_update_system_message` misc:778                     | misc:778-794                   | ✓      |
| `get_message_list` misc:190                                 | misc:190                       | ✓      |
| `MESSAGE_REPLAY_KEYS` mw:1857                               | mw:1857                        | ✓      |
| memory tools gating tools:808-814                           | tools:809-827                  | Δ      |
| file tools gating tools:733-750                             | tools:734-750 (inject 743-750) | Δ      |
| `chat`/`meta` JSON columns chats:189,198                    | chats:189, 198                 | ✓      |
| `ChatModel.meta` default `{}`                               | chats:254                      | ✓      |
| `update_chat_tags_by_id` (meta writer template)             | chats:1036-1051                | ✓      |
| `upsert_message_to_history` (meta preservation)             | chats:1148-1171                | ✓      |

**Critical discovery (PATCH A source):** `request.app.state.MODELS` redacts
`info.params` via `public_model_params` (utils/models.py:36-57), which drops `system`.
The raw Tito prompt is `model_info.params.system` from the DB row, read in main.py
(functions.py:275 `system = params.pop('system', None)` shows the templated path we
bypass). PATCH A must capture it in **main.py** (model_info loaded at main.py:1160) and
thread it through `metadata`.

## 5. Design — one helper module

`backend/open_webui/utils/tito.py` (new). Imports: stdlib (`hashlib`) + the light
`open_webui.utils.chat_id` (uuid-only; no DB/config). No import of `misc`/`config`/`db`,
so its pure functions are unit-testable without a live app.

Constants:

- `TITO_MODEL_ID = 'tito'`
- `SNAPSHOT_HEADING = 'NHỮNG ĐIỀU TITO NHỚ VỀ ÔNG'` (vet M5).
- `NO_MEMORIES_SENTINEL = '(chưa có ký ức nào)'` (vet M6).
- `MEMORY_UNAVAILABLE_SENTINEL = '(memory unavailable this chat)'` (vet M6 exact string).
- `TITO_MAX_TOKENS = 16000` (Orc O5).
- `TITO_TEMP_CHAT_ERROR` / `TITO_NO_CHAT_ERROR` (Vietnamese, Orc O3 — exact strings in KEY).

Pure functions (contract — exact names/signatures the red tests assert):

- `sha256_hex(text) -> str`
- `is_tito_model(model) -> bool`
- `tito_features() -> dict` → `{'memory': True}`
- `lock_background_tasks(tasks) -> dict` → `{'title_generation': True}` (wholesale, O5)
- `tito_stream_options() -> dict` → `{'include_usage': True}` (O5)
- `build_memory_snapshot(memories) -> str` (block2 body)
- `build_tito_blocks(prompt_raw, memories) -> tuple[str, str]` (O7: block1, block2)
- `build_tito_blocks_unavailable(prompt_raw) -> tuple[str, str]`
- `freeze_tito_system(meta, block1, block2) -> dict`
- `get_frozen_tito_system(meta) -> str | None` (combined `block1 + '\n\n' + block2`)
- `get_frozen_tito_blocks(meta) -> tuple[str, str] | None` (for the pipe breakpoint)
- `apply_frozen_system(messages, frozen_system) -> list[dict]`
- `build_tito_status(variables, budget_counters=None) -> str` (O4)
- `build_tito_status_message(status_text) -> dict` (C1: top-level `mid_conversation`)
- `store_tito_status(message, status_text) -> dict`
- `expand_tito_status(messages) -> list[dict]`
- `tito_chat_error(chat, chat_id, is_new_chat=False) -> str | None` (O3)
- `tito_memory_tool_names() -> list[str]`
- `tito_file_tool_names() -> list[str]`
- `tito_required_tool_names() -> list[str]`
- `tito_missing_tools(present_names) -> list[str]`
- `tito_model_checks(model) -> list[str]` (O6)
- `tito_config_checks(config_values) -> list[str]` (O8)

`merge_system_messages` stays in misc.py (imported mw:124, used by
`normalize_messages_for_model` mw:235); PATCH C edits it in place (§7).

## 6. PATCH A — frozen per-chat system (two blocks)

### 6.1 Requirement

1. First request of a chat for `tito`: build TWO blocks (Orc O7):
   - block1 = `model_info.params.system` **raw** (no `resolve_system_prompt`, no
     `{{ }}`, no `render_chat_variables`).
   - block2 = `SNAPSHOT_HEADING + '\n' + build_memory_snapshot(memories)`, where the
     snapshot is **all** rows from `Memories.get_memories_by_user_id`
     (models/memories.py:117), sorted `(path or '', content or '', id or '')`, each
     `path: content` if path else `content` (memory.py:43-44), one per line `- `, no
     timestamps, empty-`content` rows skipped.
2. Store BOTH blocks: `chat.meta['tito_system'] = {'block1':…, 'block2':…,
'sha256': sha256_hex(block1 + '\n\n' + block2)}` (DECISIONS + O7). Persist via the new
   meta writer (O1, §9).
3. Later turns: `combined = get_frozen_tito_system(meta)` and replay it byte-identical.
   Never re-read live `model_info.params.system` on later turns.
4. Drop every `role:system` message except `mid_conversation` ones (incl Conduit index-0
   and any MCP/skill/terminal/tool-server injection), insert exactly one system message
   = the combined frozen string at position 0.
5. Snapshot failure → `log.error` + `build_tito_blocks_unavailable` + Discord
   (`TITO_DISCORD_WEBHOOK`). Never a silent empty block.
6. Thread `metadata['tito_system'] = {'block1','block2','sha256'}` so the pipe can place
   a cache breakpoint after block1 (VERIFY-AT-RUNTIME: the pipe reads
   `__metadata__['model']['id'] == 'tito'`, main.py:1343).

### 6.2 Injection points

- **main.py** (~after model_info resolved, main.py:1160; before metadata build 1308):
  capture `tito_raw_system = model_info.params.system` when `model_id == 'tito'`; put it
  into the `metadata` dict (main.py:1308) as `metadata['tito_raw_system']`.
- **mw:process_chat_payload** (`is_tito = model.get('id') == TITO_MODEL_ID`):
  - after DB load (mw:2079-2114): `expand_tito_status` (§7) so prior statuses survive.
  - immediately before `normalize_messages_for_model` (mw:3007): O3 guard, then freeze
    (or read) `meta.tito_system`, then `apply_frozen_system`.
- Drop must run AFTER every injection (compaction mw:2160-2173, apply_system_prompt_to_body
  mw:2205-2212, voice 2354, memory 2359-2375, code-interp pyodide 2419-2423, skills
  2552/2612, MCP 2690-2695, terminal 2779, tool-server 2796) — hence just before mw:3007.

### 6.3 Impact

- `build_memory_snapshot` reads `MemoryModel` `.path/.content/.id` only (no timestamps).
- `chat.meta.tito_system` written here is read back each turn + read by the pipe's
  sha256 log (PATCH B, out of scope). `meta` is a free-form JSON column (chats:198).

## 7. PATCH C — merge leading run + status in user meta

1. `merge_system_messages` (misc.py:727) merges **only the leading run** of
   `role:system` messages. A truthy top-level `mid_conversation` key stops the run and
   passes through in place. With no leading system content, return the list unchanged.
2. Status marker = **top-level key** (Orc C1): `{"role":"system","content":…,
"mid_conversation":true}`. OWUI and pipe use exactly this.
3. Status text stored in the user message's `meta.tito_status` (O4/H2), NOT a tree node
   (no Conduit parent-resolution risk). `meta` is in `MESSAGE_REPLAY_KEYS` (mw:1857).
4. On replay, `expand_tito_status` inserts the mid_conversation system message right
   after its user message. Byte-identical on replay.

### 7.1 Backward compatibility (non-tito)

Non-tito models never emit `mid_conversation` messages (only Tito code writes the
marker), and OWUI only ever prepends system messages (`add_or_update_system_message`
misc.py:778). So leading run == old "all at index 0" for them. Guarded by
`test_backward_compatible_without_mid_conversation_marker`.

### 7.2 Status builder (Orc O4)

`build_tito_status(variables, budget_counters=None)` → `<context>\ntime: …\ntimezone: …
\nlocation: …\n</context>` from `CURRENT_DATETIME` / `CURRENT_TIMEZONE` / `USER_LOCATION`
(missing → omit that line). `budget_counters` is a hook arg, empty for now. Built in OWUI
from `metadata['variables']` (main.py:1329), NOT in the pipe. The `<context>` wrapper is
intentional: the pipe treats `<context>` as volatile and avoids putting a cache breakpoint
there (H3: never cache*control status messages). This is distinct from vet H4, which warns
against `<context>` only in the \_user-message fallback text* (a path we do not take).

Flow: build status → `build_tito_status_message` → append right after the newest user
message in `form_data['messages']` → `store_tito_status` on that user message so it
persists (O2 guarantees the re-upsert keeps it).

## 8. PATCH G — server lock (force, not just ignore)

For `model_id == 'tito'`:

1. **Ignored client inputs**: `tool_ids`, `filter_ids`, `skill_ids`, `tool_servers`,
   client `params` (esp. `reasoning_effort`, `function_calling`, `max_tokens`).
2. **FORCE `features = {'memory': True}`**, all else false (B3). Memory tools need
   `features.get('memory')` (tools.py:812).
3. **FORCE `use_builtin_tools = True`** regardless of `metadata.session_id` and
   `params.function_calling` (B2). Only gate today is mw:2070-2074.
4. **FORCE native function calling** (mw:2881-2913 native path).
5. **FORCE `params.max_tokens = 16000`** (Orc O5; vet L1) and
   **`stream_options.include_usage = True`** (Orc O5; vet H6 cost rows).
6. **Overwrite `background_tasks` wholesale** = `{title_generation: True}` (Orc O5).

Injection: `apply_tito_lock(form_data, model_id, user)` in **main.py right after
`model_id` is read (~1112)** and before `tasks = form_data.pop('background_tasks', None)`
(main.py:1116), so the later pops (tool_servers 1286, filter_ids 1324, tool_ids 1325,
features 1328) see the locked values. `use_builtin_tools` (mw:2070-2074) becomes
`is_note_chat or is_tito or (...)`.
Config (not code): grant Dad's group `features.memories` + `chat.file_upload`
(tools.py:814, 748).

## 9. O1 / O2 — model-layer support (models/chats.py)

- **O1**: new `ChatTable.update_chat_meta_by_id(id, meta_patch)` modeled on
  `update_chat_tags_by_id` (chats.py:1036-1051): reads `select(Chat.meta)`, merges, and
  `update(Chat).filter_by(id=id).values(meta={**meta, **meta_patch})`. Used to persist
  `meta.tito_system`.
- **O2**: add `'tito_status'` to the preserved-meta key list in
  `upsert_message_to_history` (chats.py:1158 set + chats.py:1166 tuple), so a re-upsert
  keeps `meta.tito_status`. Red test: `test_chat_meta.py`.

## 10. O3 — temporary / missing chat guard

For `tito`: `tito_chat_error(chat, chat_id, is_new_chat)` →

- temporary chat (`is_temporary_chat_id`) → `TITO_TEMP_CHAT_ERROR` (block, 403);
- saved chat_id but `chat is None` and NOT a brand-new chat → `TITO_NO_CHAT_ERROR`
  (loud fail);
- otherwise None.
  On error: `log.error` + Discord. A brand-new saved chat legitimately has no row yet
  (freeze path), so `is_new_chat` passes. Also block temporary chats for Dad via the
  `chat.temporary` permission (config).

## 11. B5 — startup self-check (O6/O8)

Runs once at startup, after model prefetch (main.py:453-475, before main.py:519):

1. Resolve the real Tito model dict (`app.state.MODELS['tito']`) and a real NON-admin
   user (`TITO_SELFCHECK_USER_ID`; unset → warn + skip).
2. `tito_model_checks(model)` → no `capabilities.memory=False`,
   `capabilities.file_upload=False`, `builtinTools.memory=False`.
3. `Config.get('memories.enable')` is True.
4. `tito_config_checks(...)` (O8): `ENABLE_PERSISTENT_CONFIG=False`,
   `RAG_SYSTEM_CONTEXT=False`, `memories.system_context.enable=False`.
5. Call `get_builtin_tools(request, extra_params, features=tito_features(), model,
is_note_chat=False)` with `extra_params['__user__']` = the non-admin user and a
   synthetic `metadata['files']` carrying one dummy file (exercises tools.py:734-750).
6. `tito_missing_tools(names)` empty (memory + file tools present).
7. Dump the resolved tools to the frozen file `TITO_TOOLS_FILE` (Orc C3): JSON list in
   ANTHROPIC tools format `{name, description, input_schema}` exactly as sent to the API,
   written by a dump helper. Must include file + memory + calendar + TinyFish tools.
8. Any failure: `log.error` + Discord. Also post "Tito up" line on success (vet H8).

## 12. Conflicts / decisions

- **"gated on tito" vs shared `merge_system_messages`** → change is behavior-preserving
  for non-tito (only Tito writes the marker); runs MORE tests.
- **Raw prompt source** → docs imply `model.params.system`, but it is redacted; correct
  source is `model_info.params.system` (functions.py:275).
- **`<context>` in status** → Orc O4 overrides vet H4 (H4 targets the user-message
  fallback, which we do not use). Mid-conversation status is a separate system message.
- **"chat is None → fail" vs new-chat freeze** → resolved by `is_new_chat` in the guard:
  only a follow-up with a vanished row fails loudly.
- **Gate location** (Orc C2): OWUI gates on `model['id']=='tito'` (model dict retains the
  id); the pipe gates on `__metadata__['model']['id']=='tito'` because functions.py:265-266
  rewrites the body model to base_model_id. Mark VERIFY-AT-RUNTIME.

## 13. CLAUSE → TEST table

| Clause                                   | Test                                                                      | Status                |
| ---------------------------------------- | ------------------------------------------------------------------------- | --------------------- |
| G gate id `tito`                         | `test_is_tito_model_true/false`                                           | RED                   |
| G FORCE features memory-only             | `test_tito_features_forces_memory_only`                                   | RED                   |
| G/O5 background_tasks wholesale          | `test_lock_background_tasks_wholesale_title_only` / `_empty_input`        | RED                   |
| O5 include_usage                         | `test_tito_stream_options_include_usage`                                  | RED                   |
| O5 max_tokens 16000                      | `test_tito_max_tokens_pinned`                                             | RED                   |
| A snapshot sorted/plain/no-timestamps    | `test_build_memory_snapshot_sorted_plain_no_timestamps`                   | RED                   |
| A empty → sentinel (M6)                  | `test_build_memory_snapshot_empty_returns_sentinel`                       | RED                   |
| A skip empty content                     | `test_build_memory_snapshot_skips_empty_content`                          | RED                   |
| A/O7 block1 raw, no `{{ }}` + two blocks | `test_build_tito_blocks_raw_prompt_untemplated`                           | RED                   |
| A/M5 heading markers                     | `test_build_tito_blocks_heading_avoids_volatile_markers`                  | RED                   |
| A unavailable sentinel                   | `test_build_tito_blocks_unavailable_uses_unavailable_sentinel`            | RED                   |
| O7 store both blocks + sha256            | `test_freeze_stores_two_blocks_and_sha256`                                | RED                   |
| O7 combined + blocks accessors           | `test_get_frozen_returns_combined_and_blocks`                             | RED                   |
| A absent → None                          | `test_get_frozen_returns_none_when_absent`                                | RED                   |
| A sha256 format                          | `test_sha256_hex_matches_stdlib`                                          | RED                   |
| A drop system except mid_conversation    | `test_apply_frozen_system_drops_non_mid_conversation_system_and_prepends` | RED                   |
| C1 top-level marker                      | `test_build_tito_status_message_is_marked_mid_conversation`               | RED                   |
| C/O4 status in user meta                 | `test_store_tito_status_writes_user_meta`                                 | RED                   |
| C/O4 expand after user msg               | `test_expand_tito_status_inserts_system_after_user_message`               | RED                   |
| C expand no-op                           | `test_expand_tito_status_noop_without_status_meta`                        | RED                   |
| O4 status builder all vars               | `test_build_tito_status_all_vars`                                         | RED                   |
| O4 omit missing                          | `test_build_tito_status_omits_missing_vars`                               | RED                   |
| O4 budget hook empty                     | `test_build_tito_status_budget_hook_empty_by_default`                     | RED                   |
| O3 temp chat block                       | `test_tito_chat_error_temp_chat_blocked`                                  | RED                   |
| O3 missing chat not-new                  | `test_tito_chat_error_missing_chat_not_new`                               | RED                   |
| O3 new chat ok                           | `test_tito_chat_error_ok_new_chat`                                        | RED                   |
| O3 existing ok                           | `test_tito_chat_error_ok_existing_chat`                                   | RED                   |
| O6 required names                        | `test_tito_required_tool_names_has_memory_and_file`                       | RED                   |
| O6 missing tools                         | `test_tito_missing_tools_none/reports`                                    | RED                   |
| O6 model checks                          | `test_tito_model_checks_ok/flags`                                         | RED                   |
| O8 config checks                         | `test_tito_config_checks_all_false_ok/flags_truthy`                       | RED                   |
| C merge leading run only                 | `test_merges_leading_run_only_keeps_mid_conversation_in_place`            | RED                   |
| C backward compat (must NOT break)       | `test_backward_compatible_without_mid_conversation_marker`                | green now, stay green |
| C no leading run → unchanged             | `test_no_leading_system_returns_messages_unchanged`                       | RED                   |
| C mid_conversation at front not merged   | `test_mid_conversation_system_at_front_is_not_merged_into_leading_run`    | RED                   |
| O2 tito_status preserved on re-upsert    | `test_upsert_message_to_history_preserves_tito_status`                    | RED                   |

### 13.1 NOT COVERED (and why)

| Effect                                    | Why not covered                   | Substitute check                                            |
| ----------------------------------------- | --------------------------------- | ----------------------------------------------------------- |
| `apply_tito_lock` end-to-end              | async, needs Request/Config/DB    | pure outputs tested; KISS test 1-9                          |
| `use_builtin_tools` forced (no session)   | needs full process_chat_payload   | code review mw:2070 + B5 self-check (no-session, non-admin) |
| freeze-on-first + replay byte-identical   | needs persisted Chat + two turns  | pure roundtrip; KISS system sha256 identical                |
| O1 `update_chat_meta_by_id` write         | needs DB                          | modeled on tested `update_chat_tags_by_id`; KISS replay     |
| B5 self-check runs + Discord              | needs live app + webhook          | env-gated; KISS startup line                                |
| C3 frozen-tools dump to `TITO_TOOLS_FILE` | needs resolved MCP/calendar tools | B5 self-check asserts the names; dump helper code-reviewed  |
| non-admin permission grant (config)       | not code                          | B5 self-check asserts tools for a non-admin                 |

## 14. Proof command

```
cd backend && python -m pytest open_webui/test/tito/ -q
```

Today: RED — `test_tito.py` import error (`open_webui.utils.tito` missing);
`test_merge_system_messages.py` fails the mid_conversation cases; `test_chat_meta.py`
fails the `tito_status` preservation case. After the patches: all green.
(`test_chat_meta.py` needs the full backend env; the conftest adds `backend/` to sys.path.)
