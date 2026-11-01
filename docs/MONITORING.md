# Monitoring board (Grafana)

An optional Grafana board over the pipeline's own run log, `ops.pipeline_runs`.

**What it shows:** runs logged, success rate, failed runs, latest total postings, API call success rate, retries and skipped pages,
new postings per run, total postings over time, and a table of the latest runs (status, failed task, raw records, API counters).

**What it reads:** the native PostgreSQL database that the launchd job writes to, through a
read-only role (`grafana_ro`, SELECT on `ops.pipeline_runs` only). It does not read Airflow's metadata.

**Limits (read before quoting numbers from it):**
- Run logging starts on 2026-10-27. Earlier runs (including the September load failures) exist only in `data/logs/cron.log`.
- "New postings per run" is the change in total postings since the previous logged run, not an API-call count.
- API call counters (calls, retries, pages skipped after all attempts failed) are logged per run from the first run after the
  API-logging change. Earlier runs have none, so the API panels cover only the runs since then.
- It is a local, single-machine setup (Grafana in Docker, bound to localhost), not a hosted monitoring service.

## Setup
```bash
bash docker/grafana/setup-grafana.sh                 # once: generates passwords into docker/.env, creates the read-only role
cd docker && docker compose --profile monitoring up -d grafana
open http://localhost:3000                           # user: admin, password: GRAFANA_ADMIN_PASSWORD in docker/.env
```
The dashboard "Job Market Pipeline - run log" is provisioned automatically from `docker/grafana/dashboards/`.
Stop it with `docker compose --profile monitoring down` (or `docker compose stop grafana`).
