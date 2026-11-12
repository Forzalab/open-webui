#!/usr/bin/env bash
# Nightly pg_dump -Fc of the local Postgres. Run by tito-pg-backup.timer (root).
# Retention: 14 daily + 8 weekly (Sunday copies). Never touches neon-final-*.
# Dump goes via stdout so the host (root) writes the file; /opt/tito/backups is root-only (700).
set -euo pipefail
C=/opt/tito/open-webui/tito-deploy/docker-compose.yml
ENV=/opt/tito/.env
D=/opt/tito/backups/nightly
DC=(docker compose -f "$C" --env-file "$ENV")
day=$(date -u +%F)

fail() {
  echo "Tito backup FAILED: $1" >&2
  hook=$(grep -E '^TITO_DISCORD_WEBHOOK=' "$ENV" | head -1 | cut -d= -f2- || true)
  [ -n "$hook" ] && curl -fsS -m 15 -H 'Content-Type: application/json' \
    -d "{\"content\":\"Tito backup FAILED: $1\"}" "$hook" >/dev/null 2>&1 || true
  exit 1
}
trap 'fail "step failed near line $LINENO"' ERR

umask 077
mkdir -p "$D/daily" "$D/weekly"
tmp="$D/daily/tito-$day.dump.tmp"
"${DC[@]}" exec -T postgres pg_dump -U tito -d tito -Fc -Z6 > "$tmp"
"${DC[@]}" exec -T postgres pg_restore --list < "$tmp" > /dev/null
mv "$tmp" "$D/daily/tito-$day.dump"
(cd "$D/daily" && sha256sum "tito-$day.dump" > "tito-$day.dump.sha256")

# Sunday copy = weekly
if [ "$(date -u +%u)" = 7 ]; then
  cp -p "$D/daily/tito-$day.dump" "$D/daily/tito-$day.dump.sha256" "$D/weekly/"
fi

# Retention
find "$D/daily" -name 'tito-*' -mtime +14 -delete
find "$D/weekly" -name 'tito-*' -mtime +56 -delete
echo "backup ok: tito-$day.dump $(du -h "$D/daily/tito-$day.dump" | cut -f1)"
