#!/bin/bash
# One-shot, runs as root before Airflow starts: creates writable folders, fixes ownership and
# writes the admin password file the Simple Auth Manager reads. No airflow commands here.
set -euo pipefail
OWNER="${AIRFLOW_UID:-50000}:0"
P=/opt/airflow/project

mkdir -p "$P/data/raw" "$P/data/processed" "$P/data/logs" "$P/output/excel" "$P/backups" /opt/airflow/auth

# Simple Auth Manager password file is JSON: {"username": "password"}
printf '{"admin": "%s"}\n' "${AIRFLOW_ADMIN_PASSWORD:?AIRFLOW_ADMIN_PASSWORD is not set in docker/.env}" > /opt/airflow/auth/passwords.json
chmod 600 /opt/airflow/auth/passwords.json

# chown is best-effort: some bind-mount filesystems (macOS Docker Desktop) ignore it harmlessly
chown -R "$OWNER" "$P/data" "$P/output" "$P/backups" /opt/airflow/auth /opt/airflow/logs || true
echo "prep done (owner $OWNER)"
