# FLASH-BRIEF — Tito OWUI patches A / C / G / B5 (rev 2)

For the coder. Read `SPEC.md` for the full contract. Do NOT touch the
pipe. All changes gated on `model.get('id') == 'tito'` (process_chat_payload) or
`model_id == 'tito'` (main.py).

## Acceptance criteria (numbered)

- **AC-1** `backend/open_webui/utils/tito.py` exists with exactly the constants and pure
  functions in SPEC §5 (imports: `hashlib` + `open_webui.utils.chat_id` only).
- **AC-2** `merge_system_messages` (misc.py:727) merges only the leading run and passes
  top-level `mid_conversation` messages through in place; returns the list unchanged when
  there is no leading system content. Non-tito unchanged.
- **AC-3** PATCH A: first turn freezes `block1`+`block2` into `chat.meta.tito_system`
  (`block1`, `block2`, `sha256`); later turns replay byte-identical; snapshot = ALL
  memories sorted `(path, content, id)`, no timestamps, empty rows skipped; failure →
  `build_tito_blocks_unavailable` + `log.error` + Discord.
- **AC-4** PATCH A drop: before `normalize_messages_for_model` (mw:3007), drop every
  `role:system` message except `mid_conversation`, insert exactly one frozen system at 0.
- **AC-5** PATCH C status: built by `build_tito_status` (O4 format), stored in user msg
  `meta.tito_status`, expanded after the user msg on replay (`expand_tito_status`); marker
  is the top-level `mid_conversation` key (C1).
- **AC-6** PATCH G: `apply_tito_lock(form_data, model_id, user)` in main.py right after
  `model_id` is read (before main.py:1116): strip `tool_ids`/`filter_ids`/`skill_ids`/
  `tool_servers`/client `params` (incl `reasoning_effort`); FORCE `features={'memory':True}`,
  native `function_calling`, `params.max_tokens=16000`, `stream_options.include_usage=True`,
  `background_tasks={'title_generation':True}`.
- **AC-7** `use_builtin_tools` (mw:2070-2074) forced True for `tito` regardless of
  `metadata.session_id` / `params.function_calling`.
- **AC-8** Raw prompt threaded from `model_info.params.system` in main.py
  (`metadata['tito_raw_system']`, main.py:1308); never read from redacted
  `model['info']['params']`. Also thread `metadata['tito_system']` (block1/block2/sha256)
  for the pipe breakpoint.
- **AC-9** O1: add `ChatTable.update_chat_meta_by_id(id, meta_patch)` modeled on
  `update_chat_tags_by_id` (chats.py:1036-1051). O2: add `'tito_status'` to the preserved
  meta keys in `upsert_message_to_history` (chats.py:1158 set + 1166 tuple).
- **AC-10** O3: `tito_chat_error` guard in process_chat_payload for `tito` — temporary
  chat → 403 Vietnamese + Discord; saved-but-missing chat on a follow-up → loud fail +
  Discord.
- **AC-11** O4 status builder: build `<context>…</context>` status, append as
  mid_conversation system msg after the newest user msg, `store_tito_status` on it.
- **AC-12** B5 self-check (main.py startup, after model prefetch ~475, before 519): run
  `tito_model_checks`, assert `memories.enable`, `tito_config_checks`, call
  `get_builtin_tools` with the real Tito model + a real NON-admin user (`TITO_SELFCHECK_USER_ID`),
  assert `tito_missing_tools` empty, dump `TITO_TOOLS_FILE` (C3: JSON list in Anthropic
  format `{name,description,input_schema}`), Discord on failure; warn+skip if user unset.
- **AC-13** Red tests in `backend/open_webui/test/tito/` (incl. `test_chat_meta.py`) pass
  after the patch and are red before it.

## Allowed files + line cap

- `backend/open_webui/utils/tito.py` (new) — ≤ 180 lines.
- `backend/open_webui/utils/misc.py` — edit `merge_system_messages` only (≤ +15 lines).
- `backend/open_webui/utils/middleware.py` — `use_builtin_tools` (mw:2070) + A/C hooks near
  mw:2114 and mw:3007 (≤ +50 lines).
- `backend/open_webui/models/chats.py` — O1 `update_chat_meta_by_id` (+~15 lines) + O2
  preserved-key additions (+2 lines).
- `backend/open_webui/main.py` — `apply_tito_lock` call (~1112), `tito_raw_system` +
  `tito_system` into metadata (~1308), B5 self-check + C3 dump (~475-519) (≤ +60 lines).
- Tests: `backend/open_webui/test/tito/`.
- Do NOT edit: config, CI, packages, the pipe, `env.py`, DB schema, the frontend.

## Red test = done proof

Run exactly:
```
cd backend && python -m pytest open_webui/test/tito/ -q
```
Paste its last lines. Pass = all green (incl. the backward-compat and O2 tests). If
`open_webui` is not importable in your env, that IS the red state for `test_tito.py`
(import error) — report it and note `test_merge_system_messages.py` /
`test_chat_meta.py` independently.

## Stop-and-ask rule

Stop and ask (exact question as last message) when:
- any file:line in SPEC §4/§6/§8/§9/§11 does not match the code you see;
- `model_info.params.system` is absent/empty for the `tito` model row;
- `apply_tito_lock` cannot run before main.py:1116 without breaking `title_generation`;
- `get_builtin_tools` does not expose the memory/file tools under the forced features for
  a non-admin user (permission still strips them);
- the C2 runtime gate (`__metadata__['model']['id']`) turns out NOT to equal `'tito'`;
- a change would alter behavior for any model id other than `tito`.

Do NOT guess. Do NOT implement the pipe side. Do NOT touch git.
