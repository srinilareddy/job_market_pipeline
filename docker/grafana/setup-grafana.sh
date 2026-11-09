#!/usr/bin/env bash
# One-time setup for the optional Grafana monitoring board.
#  1. appends Grafana settings to docker/.env (generated passwords; nothing is printed)
#  2. creates a READ-ONLY database role (grafana_ro) that can only SELECT from ops.pipeline_runs
# Run from anywhere:  bash docker/grafana/setup-grafana.sh
set -euo pipefail
cd "$(dirname "$0")/../.."                      # repo root
ENVF=docker/.env
[ -f .env ]    || { echo "root .env not found (it holds the DB_* settings of your native database)"; exit 1; }
[ -f "$ENVF" ] || { echo "docker/.env not found - run docker/make-env.sh first"; exit 1; }

set -a; source .env; set +a                      # DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD of the native database

[ -n "$(tail -c1 "$ENVF")" ] && echo >> "$ENVF"  # make sure the file ends with a newline
add() { grep -q "^$1=" "$ENVF" || echo "$1=$2" >> "$ENVF"; }
add GRAFANA_ADMIN_PASSWORD "$(openssl rand -hex 12)"
add GRAFANA_DB_PASSWORD    "$(openssl rand -hex 12)"
add PIPELINE_DB_PORT       "${DB_PORT}"
add PIPELINE_DB_NAME       "${DB_NAME}"
PW="$(grep '^GRAFANA_DB_PASSWORD=' "$ENVF" | tail -n1 | cut -d= -f2-)"

PGPASSWORD="$DB_PASSWORD" psql -q -h "${DB_HOST:-127.0.0.1}" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -v ON_ERROR_STOP=1 -v pw="$PW" -f - <<'SQL'
SELECT format('CREATE ROLE grafana_ro LOGIN PASSWORD %L', :'pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') \gexec
ALTER ROLE grafana_ro WITH PASSWORD :'pw';
SELECT format('GRANT CONNECT ON DATABASE %I TO grafana_ro', current_database()) \gexec
GRANT USAGE ON SCHEMA ops TO grafana_ro;
GRANT SELECT ON ops.pipeline_runs TO grafana_ro;
SQL

echo "Done. Settings were added to docker/.env (open it locally to read the Grafana admin password)."
echo "Next: cd docker && docker compose --profile monitoring up -d grafana   then open http://localhost:3000"
