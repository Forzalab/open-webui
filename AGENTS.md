# Agent notes (Forzalab fork: Tito)

This repo is Tony's **Tito** fork of Open WebUI (private AI companion for his parents).
The plan + todo list is NOT in this repo. Code `TODO` comments are upstream noise.

## Before any task: read brain first
1. Run the `brain` skill (boot / pull brain). Tito lives under project slug `personal`, not `open-webui`.
2. Read the newest `_drift/*tito*` handoff, then `projects/personal/_files/tito-selfhost-PLAN-LOCKED.md` (newest line wins).
3. Tito work branch = `tito`.

## If the brain fetch fails on credentials
Try the `BRAIN_TOKEN` env var as the GitLab token (e.g. `https://oauth2:$BRAIN_TOKEN@gitlab.com/Forzalab-bravo/brain.git`). Never print, commit, or save the token.
