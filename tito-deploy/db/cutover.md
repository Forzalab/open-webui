# Neon -> local Postgres cutover runbook

Rule kept: deploy = `up` only. Compose/bootstrap changes ship in this PR; data moves below are one-time.
Shorthand on the box (root): `DC="docker compose -f /opt/tito/open-webui/tito-deploy/docker-compose.yml --env-file /opt/tito/.env"`.
Never print `.env` values. Dump already taken: `/opt/tito/backups/neon-final-20261112T0138Z.dump`,
sha256 `e02445c8e0c5911262ee44e619516ae41bf49e300c8eedc26677ac5e5a0e98aa`. owui has been stopped since the dump,
so no writes were lost: restore that file. Take a fresh dump only if owui ran against Neon after 20261112T0138Z.

| # | Who | Step |
|---|---|---|
| 1 | orc | Merge this PR into `tito` (compose + scripts only, no image rebuild). |
| 2 | box | Checks: `df -h / /var/lib/docker` (>= 10 GB free), `free -h`, `docker compose version` (>= 2.20). `cp /opt/tito/.env /opt/tito/.env.bak-$(date +%F-%H%M)`. |
| 3 | box | In `/opt/tito/.env` add `NEON_DATABASE_URL=<current DATABASE_URL value>` (edit in place, do not print). Leave `DATABASE_URL` on Neon. |
| 4 | Tony | `up`. Postgres starts healthy with an empty `tito` DB; bootstrap generated `POSTGRES_PASSWORD`, created `/opt/tito/backups` (700) and the nightly timer. |
| 5 | box | `$DC stop owui` (keep it stopped: a started owui would run Alembic on the empty DB and break the restore). |
| 6 | box | Verify the dump: `cd /opt/tito/backups && sha256sum neon-final-20261112T0138Z.dump` equals the sha above; `$DC exec -T postgres pg_restore --list < neon-final-20261112T0138Z.dump \| head`. |
| 7 | box | "Before" fingerprint of Neon (needs Neon on Launch/unlocked; libpq URL: `postgresql://`, direct host, `sslmode=require`; if the value starts `postgresql+psycopg2://` swap the prefix): `PGURL="$(grep ^NEON_DATABASE_URL= /opt/tito/.env \| cut -d= -f2-)" /opt/tito/open-webui/tito-deploy/db/pg-verify.sh > /opt/tito/backups/neon-verify.txt`. If Neon stays locked, skip and compare against the counts you recorded before the dump. |
| 8 | box | Restore (dump streamed on stdin because the backups dir is root-only): `$DC exec -T postgres pg_restore -U tito -d tito --no-owner --no-acl --exit-on-error --jobs=1 < /opt/tito/backups/neon-final-20261112T0138Z.dump` then `$DC exec -T postgres psql -U tito -d tito -c 'ANALYZE;'`. Failed half way: `$DC exec -T postgres psql -U tito -d postgres -c 'DROP DATABASE tito' -c 'CREATE DATABASE tito OWNER tito'` and rerun. |
| 9 | box | Local fingerprint and diff: `PGURL=postgresql://tito@localhost/tito /opt/tito/open-webui/tito-deploy/db/pg-verify.sh > /opt/tito/backups/local-verify.txt; diff /opt/tito/backups/neon-verify.txt /opt/tito/backups/local-verify.txt` must be empty. Spot checks: memory counts per user (dinh >= 20, ngan >= 26), Dad's chat `2216b4ab%` exists, `select pg_size_pretty(pg_database_size('tito'))`. |
| 10 | box | `.env`: set `DATABASE_URL=postgresql://tito:<POSTGRES_PASSWORD value>@postgres:5432/tito` (copy the value inside the file). Keep `TITO_IMAGE_TAG` at the last good tag (`tito-74369dd3...`). |
| 11 | Tony | `up`. OWUI starts on local Postgres. |
| 12 | box+orc | Check: `$DC ps` (postgres healthy, owui healthy, caddy up); owui log has no Alembic error; `/health` 200 on both domains; logins `dinh`, `ngan`, Tony Google; Dad's chat opens; memory counts equal "before"; model `tito`, tools, function `anthropic` present; one API test turn (then delete the chat); `select count(*) from pg_stat_activity where datname='tito'` <= 20. |
| 13 | box | `.env`: `TITO_IMAGE_TAG=tito-888e99b8...`, Tony `up`. Same migrations as step 10's image, so no schema change. |
| 14 | box+orc | `GET /api/v1/tito/interject` with admin key -> 200; self-check passes; one more test turn. Next morning: first file in `/opt/tito/backups/nightly/daily/` with sha256 ok (`systemctl list-timers tito-pg-backup.timer`, `journalctl -u tito-pg-backup`). |
| 15 | Tony | Day 3-7: delete the Neon project, downgrade org to Free, then remove `NEON_DATABASE_URL` from `.env`. |

## Rollback
- Before step 11: nothing changed for users. Restore `.env` from the `.env.bak-*` copy (or leave `DATABASE_URL` on Neon), `up`.
- After step 11, soon after: `$DC stop owui`, set `DATABASE_URL` back to the `NEON_DATABASE_URL` value, `up`. Writes made on local after step 11 are lost unless moved by hand: decide fast.
- Local data broken later: restore the newest `nightly/daily/*.dump` (same `pg_restore < file` pattern as step 8 into a fresh DB) or `neon-final-*.dump`.
- Never alternate owui between both DBs without a plan: the newer side wins, the other side's new writes are lost.

## Nightly backup
`db/backup.sh` via `tito-pg-backup.timer` (11:30 UTC): `pg_dump -Fc` to `/opt/tito/backups/nightly/daily/`, verified with `pg_restore --list`, sha256 beside it, Sunday copy to `weekly/`. Retention 14 daily + 8 weekly; `neon-final-*` never touched. Failure posts "Tito backup FAILED" to `TITO_DISCORD_WEBHOOK`.
Not covered: the `owui-data` volume (uploads, chroma, tito-tools.json) is not backed up yet.

## TODO (not tonight)
- Encrypted off-box copy to brain (age public key on box, daily increments; design section 10). Stub only.
- Monthly restore test into a scratch DB.
