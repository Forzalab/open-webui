#!/usr/bin/env bash
# Print a deterministic fingerprint of a Postgres DB: per-table exact counts, md5 of key tables,
# sequences, alembic version. Run on both sides, then diff.
#   NEON=$(grep ^NEON_DATABASE_URL= /opt/tito/.env | cut -d= -f2-)   # libpq form: postgresql://...
#   PGURL="$NEON" ./pg-verify.sh > neon.txt ; PGURL="postgresql://tito@localhost/tito" ./pg-verify.sh > local.txt
#   diff neon.txt local.txt   # must be empty
# URL comes from $PGURL (not argv, never printed). Runs psql inside the postgres container (v17 client).
# For local (inside the container) use: postgresql://tito@localhost/tito (trust on local socket/loopback).
set -euo pipefail
: "${PGURL:?set PGURL}"
C=/opt/tito/open-webui/tito-deploy/docker-compose.yml
KEY="user auth chat chat_message memory model function tool skill config file access_grant api_key"

SQL=$(cat <<SQL_END
\\pset format unaligned
\\pset tuples_only on
select '## counts';
select table_name || E'\\t' || (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from public.%I', table_name), false, true, '')))[1]::text
  from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by table_name;
select '## md5 (key tables)';
select table_name || E'\\t' || coalesce((xpath('/row/c/text()', query_to_xml(format('select md5(string_agg(md5(t::text), %L order by md5(t::text))) as c from public.%I t', '', table_name), false, true, '')))[1]::text, 'empty')
  from information_schema.tables where table_schema='public' and table_type='BASE TABLE'
   and table_name = any(string_to_array('$KEY', ' ')) order by table_name;
select '## sequences';
select sequencename || E'\\t' || coalesce(last_value::text, 'null') from pg_sequences where schemaname='public' order by 1;
select '## alembic';
select version_num from alembic_version;
select 'migratehistory' || E'\\t' || count(*) from migratehistory;
SQL_END
)
# migratehistory may not exist; tolerate that last query only.
printf '%s\n' "$SQL" | docker compose -f "$C" --env-file /opt/tito/.env exec -T -e PGURL postgres sh -c 'psql "$PGURL" -X -q -v ON_ERROR_STOP=0 2>&1'
