# SPEC — Tito OWUI-side patches (A, C, G, B5)

Status: PRO spec (do NOT implement). Companion to `FLASH-BRIEF.md` (ACs for the coder)
and `KEY.md` (answers/expected values). All changes are gated on **model id `"tito"`**;
every other model's request path is byte-for-byte unchanged.

## 1. Goal

Freeze Tito's per-chat system prompt and tool configuration so that every turn of a
chat replays an identical prefix (cache-stable, no 400s), independent of:
client-sent UI state (features / tool_ids / filter_ids / skill_ids / tool_servers /
params), Conduit's injected system message, live prompt edits, or a dead websocket.
Plus a loud startup self-check that the frozen tool list is actually attainable for a
NON-admin user.

## 2. Why

- Anthropic prompt caching keys on the message prefix. Any drift (a changed tool array,
  a re-read live system prompt, a mid-conversation status node moving) rebuilds the
  cache and can mismatch preserved `thinking` blocks → 400 or silent quality drop
  (vet B1–B4, H1–H3).
- Dad is a non-admin user; Tony tests as admin. Admin bypasses permission gates
  (mw:2366 `role == 'admin' or has_permission`), so Tony's green test proves nothing
  about Dad's request (vet B5).
- Conduit sends `session_id` only when a socket is alive; without it OWUI drops all
  builtin tools (mw:2070-2074) (vet B2).

## 3. Non-goals (explicitly OUT of this spec)

- Pipe patches B (fixed config dict, no nudge/terminal hint, sha256 log), D
  (status → role:system mid-conversation message + beta header + cache breakpoint),
  F (keepalive — already CUT), the budget gate, and the frozen-tool-spec file. Those
  live in the Podden pipe fork, not `backend/open_webui/`.
- The memory-as-file variant (rejected; DECISIONS Q18 keeps snapshot as system block 2).
- Mid-chat Haiku swap (CUT), keepalive (CUT), "still here" gesture (CUT).

## 4. Verified file:line map (docs → real code)

Docs use short names (`mw` = `backend/open_webui/utils/middleware.py`,
`misc` = `backend/open_webui/utils/misc.py`, `tools` = `backend/open_webui/utils/tools.py`,
`chats` = `backend/open_webui/models/chats.py`, `memories` = `backend/open_webui/models/memories.py`).
A ✓ means exact; a Δ means the doc's line was off and the real location is used.

| Doc claim | Real location | Status |
|---|---|---|
| `use_builtin_tools` mw:2069-2073 | mw:2070-2074 | Δ (+1) |
| `chat = get_chat_by_id` mw:2068 | mw:2068 | ✓ |
| `load_messages_from_db` drops empty assistant mw:1879-1883 | fn mw:1860, filter mw:1882 | Δ |
| re-attach system after DB load mw:2110-2111 | mw:2113-2114 | Δ |
| `apply_system_prompt_to_body` replace mw:2205 | mw:2205-2212 | ✓ |
| `variables = pop` mw:2322 | mw:2322 | ✓ |
| `features = pop` mw:2345 | mw:2345 | ✓ |
| memory permission check (admin bypass) mw:2366 | mw:2366 | ✓ |
| `tool_ids = pop` mw:2426 | mw:2426 | ✓ |
| `skill_ids` mw:2482-2483 | mw:2482-2483 | ✓ |
| MCP `instructions` into system mw:2691 | mw:2690-2695 | ✓ |
| MCP connect failure `log.exception + continue` mw:2725-2740 | mw:2725-2739 | Δ |
| terminal system prompt mw:2779 | mw:2779 | ✓ |
| tool-server system prompt mw:2796 | mw:2796 | ✓ |
| builtin tools injection mw:2826-2829 | mw:2828-2872 (call mw:2854) | ✓ |
| `is_file_context_enabled` mw:2926-2932 | fn tools:588-593, call mw:2926 | Δ |
| `normalize_messages_for_model` → `merge_system_messages` | mw:233-236, call mw:3007 | ✓ |
| `merge_system_messages` misc:727 | misc:727-751 | ✓ |
| `add_or_update_system_message` misc:778 | misc:778-794 | ✓ |
| `get_message_list` misc:190 | misc:190 | ✓ |
| `MESSAGE_REPLAY_KEYS` mw:1857 | mw:1857 | ✓ |
| memory tools gating tools:808-814 | tools:809-827 | Δ |
| file tools gating tools:733-750 | tools:734-750 (inject 743-750) | Δ |
| `chat`/`meta` JSON columns chats:189,198 | chats:189, 198 | ✓ |
| `ChatModel.meta` default `{}` | chats:254 | ✓ |

**Critical discovery (affects PATCH A source):** the model dict in
`request.app.state.MODELS` has its `info.params` **redacted** by `public_model_params`
(utils/models.py:36-57), which drops `system`. So the raw Tito prompt is NOT readable
from `model['info']['params']['system']` inside `process_chat_payload`. The raw prompt
is `model_info.params.system` from the DB row, read in main.py at the point functions.py
would otherwise template it (`functions.py:275` `system = params.pop('system', None)`).
PATCH A must capture it in **main.py** (where `model_info` is already loaded at
main.py:1160) and thread it through `metadata`.

## 5. Design — one helper module

`backend/open_webui/utils/tito.py` (new). Imports only stdlib (`hashlib`, `typing`) and
nothing from `open_webui` that pulls DB/config, so its pure functions are unit-testable
without a live app. Pure functions + one thin async wrapper.

Constants:
- `TITO_MODEL_ID = 'tito'`
- `SNAPSHOT_HEADING = 'NHỮNG ĐIỀU TITO NHỚ VỀ ÔNG'` (vet M5: must NOT contain the pipe's
  volatile markers `<memory_context>` — memory.py:17-18 — nor `User Context:`).
- `NO_MEMORIES_SENTINEL = '(chưa có ký ức nào)'` (vet M6: explicit sentinel when empty).
- `MEMORY_UNAVAILABLE_SENTINEL = '(memory unavailable this chat)'` (vet M6 exact string).

Pure functions (contract — these exact names/signatures are what the red tests assert):
- `sha256_hex(text: str) -> str`
- `is_tito_model(model: dict) -> bool`
- `tito_features() -> dict`  → `{'memory': True}` (B3)
- `lock_background_tasks(tasks: dict) -> dict` → removes `follow_up_generation` and
  `tags_generation`, keeps `title_generation` (PATCH G).
- `build_memory_snapshot(memories) -> str` (PATCH A block 2)
- `build_tito_system(prompt_raw: str, memories) -> str` (block1 + block2)
- `build_tito_system_unavailable(prompt_raw: str) -> str`
- `freeze_tito_system(meta: dict, system: str) -> dict`
- `get_frozen_tito_system(meta: dict) -> str | None`
- `apply_frozen_system(messages: list[dict], frozen_system: str) -> list[dict]`
- `build_tito_status_message(status_text: str) -> dict`
- `store_tito_status(message: dict, status_text: str) -> dict`
- `expand_tito_status(messages: list[dict]) -> list[dict]`

`merge_system_messages` lives in misc.py (already imported by mw:124 and used by
`normalize_messages_for_model`, mw:235); PATCH C edits it in place (see §7).

## 6. PATCH A — frozen per-chat system

### 6.1 Requirement

1. First request of a chat for `tito`: build the full system as
   `block1 + '\n\n' + SNAPSHOT_HEADING + '\n' + block2`, where:
   - block1 = `model_info.params.system` **raw** (no `resolve_system_prompt`, no
     `{{ }}` substitution, no `render_chat_variables`).
   - block2 = memory snapshot: **all** rows from `Memories.get_memories_by_user_id`
     (models/memories.py:117), sorted by `(path or '', content or '', id or '')`,
     each rendered `path: content` if path else `content` (memory_label format,
     memory.py:43-44), one per line prefixed `- `, **no timestamps**; rows with
     `None`/empty `content` are skipped.
2. Store `chat.meta['tito_system'] = {'system': <full system>, 'sha256': sha256_hex(...)}`
   (DECISIONS: meta.tito_system + sha256). Persist it.
3. Later turns: read `chat.meta.tito_system.system` and replay it **byte-identical**.
   Never re-read live `model_info.params.system` on later turns.
4. Drop every `role:system` message **except** ones marked `mid_conversation` (the
   status messages), including Conduit's index-0 system message and any MCP/skill/
   terminal/tool-server instruction that was injected earlier.
5. Insert exactly one system message = the frozen system at position 0.
6. Snapshot build failure (exception fetching/formatting memories) → `log.error`,
   use `build_tito_system_unavailable`, post to `TITO_DISCORD_WEBHOOK`. Never a silent
   empty block.

### 6.2 Injection points

- **main.py** (~after model_info resolved, main.py:1160; before metadata build 1308):
  capture `tito_raw_system = model_info.params.system` when `model_id == 'tito'`, and
  put it into the `metadata` dict built at main.py:1308 (new key `tito_raw_system`).
- **mw:process_chat_payload**:
  - `is_tito = model.get('id') == TITO_MODEL_ID` (id field used at mw:2192).
  - After DB messages are loaded (mw:2079-2114), if `is_tito`: expand status
    (§7) so mid_conversation status survives to the end.
  - Immediately before `normalize_messages_for_model` (mw:3007), if `is_tito`:
    `frozen = get_frozen_tito_system((chat.meta) or {})`; if `None` build from
    `metadata['tito_raw_system']` + snapshot, persist via `Chats.update_chat_by_id`
    (chats:854) writing `meta.tito_system`; then
    `form_data['messages'] = apply_frozen_system(form_data['messages'], frozen)`.
- The drop must run AFTER every injection listed in the audit (compaction summary
  mw:2160-2173, apply_system_prompt_to_body mw:2205-2212, voice 2354, memory 2359-2375,
  code-interpreter pyodide 2419-2423, skills 2552/2612, MCP 2690-2695, terminal 2779,
  tool-server 2796) — hence immediately before mw:3007.

### 6.3 Impact (who reads what)

- `build_memory_snapshot` reads `MemoryModel` rows (`path`, `content`, `id`) — no
  dependency on `updated_at`/`created_at` (invariant: no timestamps).
- `chat.meta` written here is read back on every later turn via `get_frozen_tito_system`;
  it is also read by the pipe's sha256 log (PATCH B, out of scope) as the prefix.
- Nothing else reads `meta.tito_system`; `meta` is a free-form JSON column
  (chats:198) so no schema change.

## 7. PATCH C — merge leading run + status in user meta

### 7.1 Requirement

1. `merge_system_messages` (misc.py:727) merges **only the leading run** of
   `role:system` messages. A message with a truthy `mid_conversation` key stops the
   leading run and is passed through in place. With no leading system content, return
   the list unchanged (do NOT drop mid_conversation messages, unlike today).
2. Status text is stored in the **user message's `meta`** under `meta.tito_status`
   (vet H2), not as a separate node — so the parentId tree is unchanged and Conduit's
   parent resolution is unaffected. `meta` is already in `MESSAGE_REPLAY_KEYS`
   (mw:1857), so it replays.
3. On replay, `expand_tito_status` inserts a `{'role':'system','content':status,
   'mid_conversation': True}` message immediately after the user message that carries
   `meta.tito_status`, so the pipe (PATCH D) can render it as a real mid-conversation
   system message. Byte-identical on replay.

### 7.2 Backward compatibility (non-tito)

Non-tito models never emit `mid_conversation`-marked messages (the marker is only
written by Tito code). For them the leading run == the old "all system messages at
index 0" (OWUI only ever prepends system messages — `add_or_update_system_message`
misc.py:778). So behavior is unchanged; guarded by
`test_backward_compatible_without_mid_conversation_marker`.

### 7.3 Injection points

- `merge_system_messages` edit is local to misc.py:727-751.
- `expand_tito_status` is called in process_chat_payload for `tito` right after
  db_messages are loaded (mw:2114) and before `apply_frozen_system` (which drops
  non-mid_conversation system messages, §6.2).
- The **status builder** (who computes the time/location/budget text) is a separate
  integration concern; this spec only fixes its storage/expansion mechanism. Its
  persistence is `store_tito_status` on the user message before the turn is saved.

## 8. PATCH G — server lock (with Fable fixes B2/B3)

### 8.1 Requirement (force, not just ignore)

For `model_id == 'tito'`, the server:
1. **Ignored client inputs** (stripped/neutralized in `form_data`): `tool_ids`,
   `filter_ids`, `skill_ids`, `tool_servers`, and `params` (esp. `reasoning_effort`,
   `function_calling`, and any other client `params` key). Fable B1: Conduit sends
   `reasoning_effort` from its picker (must be stripped so the pipe's fixed dict wins).
2. **FORCE `features = {'memory': True}`** and every other feature key false/absent
   (B3). This is what keeps memory tools injectable (tools.py:809-827 requires
   `features.get('memory')`), and it must NOT remove them — "ignore client features"
   alone would strip memory tools.
3. **FORCE `use_builtin_tools = True`** regardless of `metadata.session_id` and
   `params.function_calling` (B2). This is what keeps memory + file + time tools
   injected when Conduit has no live socket (mw:2070-2074 is the only gate today).
4. **FORCE native function calling** (`function_calling` != `'legacy'`) so builtin
   tools go the native path (mw:2881-2913).
5. **background_tasks: follow_up_generation and tags_generation off**; keep
   `title_generation` (title runs on the external Haiku task model, not Tito).

### 8.2 Injection points

- `apply_tito_lock(form_data, model_id, user)` (async) called in **main.py right after
  `model_id` is read** (main.py ~1112) and **before** `tasks =
  form_data.pop('background_tasks', None)` (main.py:1116), so:
  - `background_tasks` is already stripped when main.py:1116 pops it;
  - `tool_servers` (popped main.py:1286), `filter_ids` (1324), `tool_ids` (1325),
    `features` (1328) are already cleared/forced when main.py reads them.
- `use_builtin_tools` (mw:2070-2074): change to `is_note_chat or is_tito or (...)` so
  the lock's native-`function_calling` + session-absence cannot drop builtin tools.
- Config (not code, but required for the patch to work): Dad's group must be granted
  `features.memories` and `chat.file_upload` permissions (tools.py:814/748), else the
  non-admin permission check (tools.py:673-680) strips the very tools we forced.

## 9. B5 — startup self-check

### 9.1 Requirement

A startup self-check that, for a **NON-admin** user id, builds Tito's tool list and
asserts the expected tool names are present (memory tools + file tools); on failure
`log.error` + POST to `TITO_DISCORD_WEBHOOK` (env).

Expected names (SOURCE of each):
- memory tools (tools.py:816-827): `search_memories`, `list_memory_paths`,
  `read_memory_path`, `list_memories`, `update_memory`, `add_memory`,
  `replace_memory_content`, `delete_memory`.
- file tools (tools.py:750): `list_chat_files`, `query_chat_files`, `grep_chat_files`,
  `view_file`, `display_file`.

### 9.2 Mechanics

- Runs once in the app startup path, after models are prefetched (main.py:453-475,
  before `app.state.startup_complete = True` at main.py:519).
- Needs the non-admin user id: configurable via env `TITO_SELFCHECK_USER_ID` (fallback:
  an email → resolve via `Users`). The user must be verified NON-admin; if the id is
  unset, log a warning and skip (do not crash startup).
- Builds the tool list by calling `get_builtin_tools` (tools.py:634) with a synthetic
  `extra_params` carrying `__user__` for that user, `features = tito_features()`, and a
  `metadata` whose `files` contains one dummy file so the file-tool branch
  (tools.py:734-750) is exercised, and `params.function_calling == 'native'`.
- Assert every expected name is in the returned dict. Memory tools must be present
  regardless of any file; file tools present because of the dummy file.

## 10. Conflicts / decisions

- **"gated on tito" vs. shared `merge_system_messages`.** The plan says change
  misc.py:727; the brief says "other models unchanged". Resolution: the change is
  behavior-preserving for non-tito because only tito code ever writes the
  `mid_conversation` marker (§7.2). Chosen because it runs MORE tests (the merge
  regression test stays green for old-style messages) and avoids a model-id branch in
  a pure function.
- **Raw prompt source.** Docs imply `model.params.system`; real code redacts it
  (§4 discovery). Resolution: source from `model_info.params.system` in main.py. This
  is the only correct source; the alternative (re-fetch model_info in
  process_chat_payload) doubles the DB hit and is rejected.
- **Memory snapshot = "all" memories.** recall_memories only surfaces `type=='user'`
  (memory.py:326); the snapshot must be ALL rows (both types) per DECISIONS. Resolution:
  no type filter; sort by `(path, content, id)`.

## 11. CLAUSE → TEST table

| Clause | Test | Status |
|---|---|---|
| G: gate on id `tito` | `test_is_tito_model_true_for_id_tito` / `..._false_for_other_id` | RED |
| G: FORCE features memory-only | `test_tito_features_forces_memory_only` | RED |
| G: follow_up/tags off, title on | `test_lock_background_tasks_strips_follow_up_and_tags_keeps_title` | RED |
| A: snapshot sorted/plain/no-timestamps | `test_build_memory_snapshot_sorted_plain_no_timestamps` | RED |
| A: empty → sentinel (M6) | `test_build_memory_snapshot_empty_returns_sentinel` | RED |
| A: skip empty content rows | `test_build_memory_snapshot_skips_empty_content` | RED |
| A: block1 raw, no `{{ }}` | `test_build_tito_system_raw_prompt_untemplated` | RED |
| A: heading + snapshot, M5 markers | `test_build_tito_system_contains_heading_and_snapshot` | RED |
| A: unavailable sentinel | `test_build_tito_system_unavailable_uses_unavailable_sentinel` | RED |
| A: meta.tito_system + sha256 | `test_freeze_and_get_frozen_system_roundtrip_with_sha256` | RED |
| A: absent → None (first turn) | `test_get_frozen_tito_system_returns_none_when_absent` | RED |
| A: sha256 hex format | `test_sha256_hex_matches_stdlib` | RED |
| A: drop system except mid_conversation + prepend | `test_apply_frozen_system_drops_non_mid_conversation_system_and_prepends` | RED |
| C: status marked mid_conversation | `test_build_tito_status_message_is_marked_mid_conversation` | RED |
| C: status in user meta | `test_store_tito_status_writes_user_meta` | RED |
| C: expand after user msg | `test_expand_tito_status_inserts_system_after_user_message` | RED |
| C: expand no-op w/o status | `test_expand_tito_status_noop_without_status_meta` | RED |
| C: merge leading run only | `test_merges_leading_run_only_keeps_mid_conversation_in_place` | RED |
| C: backward compat (must NOT break) | `test_backward_compatible_without_mid_conversation_marker` | green now, must stay green |
| C: no leading run → unchanged | `test_no_leading_system_returns_messages_unchanged` | RED |
| C: mid_conversation at front not merged | `test_mid_conversation_system_at_front_is_not_merged_into_leading_run` | RED |

### 11.1 NOT COVERED (and why)

| Effect | Why not covered | Substitute check |
|---|---|---|
| `apply_tito_lock` end-to-end (strips form_data, forces features) | async, needs Request/Config/DB; not a pure function | red-tested via its pure outputs (`tito_features`, `lock_background_tasks`, `is_tito_model`); integration verified in KISS test 1-9 |
| `use_builtin_tools` forced True with no session | requires full `process_chat_payload` + DB chat | covered by code review of mw:2070-2074 + B5 self-check asserting tools exist for a non-admin (no session) user |
| freeze-on-first-request + replay-byte-identical | requires persisted Chat row + two live turns | unit-tested pure roundtrip (`freeze`/`get_frozen`); byte-identical replay asserted in KISS (system sha256 identical within chat) |
| `meta.tito_system` persistence write | needs DB Chat row | `Chats.update_chat_by_id` is existing, tested code; KISS asserts replay |
| B5 self-check runs + Discord | needs live app + webhook | env-gated; asserted in KISS startup line "Tito up … tools sha" |
| non-admin permission grant (config) | not code; env/UI config | B5 self-check is the assertion |
| Conduit edit/regenerate after status msg | needs client | KISS test 9 (regenerate) + H2 (no node in tree) |

## 12. Proof command

```
cd backend && python -m pytest open_webui/test/tito/ -q
```
Expected today: RED — `test_tito.py` fails at import (`ModuleNotFoundError:
open_webui.utils.tito`); `test_merge_system_messages.py` fails on the mid_conversation
cases. After the patches: all green. (Requires the OWUI venv with pytest-asyncio and
the `open_webui` package importable; the test conftest adds `backend/` to sys.path.)
