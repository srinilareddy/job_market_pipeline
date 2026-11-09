#!/bin/bash
# Runs once, on first start of an empty data volume (official postgres image behaviour).
# POSTGRES_DB (job_market) is created by the image; Airflow's metadata DB is created here.
# 02-init_db.sql (mounted from src/db/init_db.sql) then creates the pipeline tables.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -c "CREATE DATABASE airflow OWNER \"$POSTGRES_USER\""
