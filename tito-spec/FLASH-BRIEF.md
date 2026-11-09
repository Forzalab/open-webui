# FLASH-BRIEF — Tito OWUI patches A / C / G / B5

For the coder. Read `SPEC.md` for the full contract; `KEY.md` for answers. Do NOT touch
the pipe. All changes gated on `model.get('id') == 'tito'` (or `model_id == 'tito'` in
main.py).

## Acceptance criteria (numbered)

- **AC-1** `backend/open_webui/utils/tito.py` exists with exactly the constants and
  pure-function signatures listed in SPEC §5 (imports: stdlib only).
- **AC-2** `merge_system_messages` (misc.py:727) merges only the leading run and passes
  `mid_conversation`-marked system messages through in place; returns the list unchanged
  when there is no leading system content. Non-tito messages merge exactly as before.
- **AC-3** PATCH A: first turn of a `tito` chat freezes `block1 + SNAPSHOT_HEADING +
  snapshot` into `chat.meta.tito_system` (`system` + `sha256`); later turns replay it
  byte-identical; snapshot built from ALL memories, sorted `(path, content, id)`, no
  timestamps; failure → `MEMORY_UNAVAILABLE_SENTINEL` + `log.error` + Discord.
- **AC-4** PATCH A drop: before `normalize_messages_for_model` (mw:3007), drop every
  `role:system` message except `mid_conversation` ones, and insert exactly one frozen
  system at position 0.
- **AC-5** PATCH C status: status stored in user msg `meta.tito_status`
  (`store_tito_status`), expanded to a `mid_conversation` system message after the user
  msg on replay (`expand_tito_status`).
- **AC-6** PATCH G: `apply_tito_lock(form_data, model_id, user)` called in main.py right
  after `model_id` is read (before main.py:1116) strips `tool_ids`/`filter_ids`/
  `skill_ids`/`tool_servers`/client `params` (incl. `reasoning_effort`), forces
  `features={'memory': True}`, native `function_calling`, and strips
  `follow_up_generation`/`tags_generation` (keeps `title_generation`).
- **AC-7** `use_builtin_tools` (mw:2070-2074) is forced True for `tito` regardless of
  `metadata.session_id` / `params.function_calling`.
- **AC-8** Raw prompt is threaded from `model_info.params.system` in main.py (add
  `metadata['tito_raw_system']` at the metadata build, main.py:1308), NOT read from the
  redacted `model['info']['params']`.
- **AC-9** B5 startup self-check (main.py startup path, after model prefetch main.py:475,
  before main.py:519) builds the tool list for a NON-admin user (`TITO_SELFCHECK_USER_ID`
  env) and asserts memory + file tool names; failure → `log.error` + Discord
  (`TITO_DISCORD_WEBHOOK`). Skip with a warning if the user id is unset.
- **AC-10** Red tests in `backend/open_webui/test/tito/` all pass after the patch and
  are red before it.

## Allowed files + line cap

- `backend/open_webui/utils/tito.py` (new) — ≤ 180 lines.
- `backend/open_webui/utils/misc.py` — edit `merge_system_messages` only (≤ +15 lines).
- `backend/open_webui/utils/middleware.py` — edit `use_builtin_tools` (mw:2070) and add
  the PATCH A/C hooks near mw:2114 and mw:3007 (≤ +40 lines total).
- `backend/open_webui/main.py` — add `apply_tito_lock` call (~1112), `tito_raw_system`
  into metadata (~1308), and B5 self-check (~475-519) (≤ +50 lines total).
- Tests: `backend/open_webui/test/tito/` (already present; you may add tests, do not
  weaken existing ones).
- Do NOT edit: config, CI, packages, the pipe, `env.py`, DB models, the frontend.

## Red test = done proof

Run exactly:
```
cd backend && python -m pytest open_webui/test/tito/ -q
```
Paste its last lines. Pass = all tests green, including the two backward-compat /
must-not-break tests. If `open_webui` is not importable in your env, that IS the red
state for `test_tito.py` (import error) — report it and note that `test_merge_system_messages.py`
is independently red/green.

## Stop-and-ask rule

Stop and ask (put the exact question as your last message) when:
- any file:line in SPEC §4/§6/§8 does not match the code you see;
- `model_info.params.system` is absent/empty for the `tito` model row, or
  `public_model_params` has changed;
- `apply_tito_lock` cannot run before main.py:1116 without breaking `title_generation`;
- the B5 self-check cannot obtain a non-admin user (no `TITO_SELFCHECK_USER_ID` and no
  non-admin user exists);
- a change would alter behavior for any model id other than `tito`.

Do NOT guess. Do NOT implement the pipe side. Do NOT touch git.
