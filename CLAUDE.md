# CLAUDE.md — Job Market Analytics Pipeline

Read this first. It describes the project as it exists in the source code. Verify anything you plan to
quote against the code, `docs/metrics.sql`, or the database. Labels used in `docs/`:
**[V]** verified in code or logs, **[I]** inferred, **[P]** proposed, not implemented.

## Overview
A daily ELT pipeline that collects U.S. data and software job postings from the Adzuna REST API, cleans
and models them in PostgreSQL (Bronze → Silver → Gold), runs quality checks, and produces an Excel KPI
scorecard. An Airflow DAG and a Docker Compose stack package the same steps. A launchd job runs the
native pipeline daily.

## Technology stack [V]
- Python with pandas, SQLAlchemy 2, psycopg2, requests, python-dotenv, xlsxwriter (`requirements.txt`)
- PostgreSQL (star schema in `public`, marts in schema `gold`, run log in `ops`)
- Apache Airflow DAG (`dags/job_market_pipeline.py`), Docker Compose (`docker/`)
- Grafana board (optional, read-only role on `ops.pipeline_runs`)
- GitHub Actions CI (pytest on Python 3.12)
- Power BI and DAX drafts in `powerbi/` (not built)

## Architecture and key code
| Layer | Code | Output |
|---|---|---|
| Bronze | `src/ingestion/fetch_jobs.py` | `data/raw/adzuna_*.json` (15 terms × 3 pages × 50 results) |
| Silver | `src/transform/clean_transform.py` + `skill_extractor_hybrid.py` | `data/processed/jobs_clean_*.csv`, `job_skills_*.csv` |
| Silver load | `src/db/load_to_db.py` | `jobs_fact`, `companies_dim`, `locations_dim`, `skills_dim`, `job_skills_bridge` |
| Quality | `src/db/quality_checks.py` | fails the run on bad data |
| Gold | `src/db/gold_layer.sql`, `src/db/gold_ops.py` | `gold.fct_jobs`, `gold.fct_job_skills`, `gold.skill_demand_by_role`, `gold.salary_by_state_role`, `ops.pipeline_runs` |
| Publish | `src/export/export_excel.py` | `output/excel/job_market_scorecard_<date>.xlsx` |
| Orchestration (native) | `src/run_pipeline.py` | runs the steps in order, launchd at 08:00 |
| Orchestration (Airflow) | `dags/job_market_pipeline.py` | 10 tasks, validation gates, Slack hook |

## Setup and execution
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # Adzuna + Postgres credentials (never commit)
createdb job_market
psql job_market -f src/db/init_db.sql      # fresh install only: DROPs tables
psql job_market -f src/db/gold_layer.sql
python src/run_pipeline.py                 # full run
python src/export/export_excel.py
python -m pytest tests/ -q
```
Docker: `cd docker && ./make-env.sh && docker compose build && docker compose up -d` (see `docs/DOCKER.md`).

## Implemented features [V]
- Adzuna fetch with per-page retries and API call/retry/failure counters, written to the run log
- Cleaning: whitespace normalisation, missing-ID fallback to a content hash, de-duplication
- Salary flag: each posting keeps Adzuna's `salary_is_predicted`. Gold salary statistics use employer-stated values only.
- Rule-based skill extraction with a hybrid dictionary, ambiguity rules for short names (for example "Go"), and alias merging
- Star-schema load with upserts and `ON CONFLICT` handling
- Quality checks: zero jobs, null titles, duplicate source IDs, literal "NaN" text, NaN salary values
- Gold materialized views refreshed each run; run log in `ops.pipeline_runs`
- Excel scorecard with live formulas over Excel Tables
- 15 pytest tests (12 for the skill extractor, 3 for fetch), run in CI
- Airflow DAG with bronze/silver/gold/publish task groups, validation gates, retries, `max_active_runs=1`

## Known issues and limitations [V unless marked]
- **Two orchestrators write to the same database.** The launchd job (`run_pipeline.py`) and the Airflow DAG each run the pipeline. The DAG's `max_active_runs` only prevents overlap within Airflow, not with launchd. **[I]** this could overlap if both run.
- `src/transform/skill_extractor.py` is an empty file. The working module is `skill_extractor_hybrid.py`.
- "Newest file" is defined two ways: `validate_raw` uses file modification time, while `clean_transform.py` and `load_to_db.py` use the timestamp in the filename.
- Skill matching keys on `raw_hash`. If two different postings share a hash, the bridge may attach skills to the wrong `job_pk`. **[I]** edge case, not tested.
- Adzuna truncates descriptions (about 500 characters). Only 35.4% of postings have a detected skill (README), so skill counts are lower bounds.
- `role_family` is a regex on titles. "Other" share should be checked before quoting role figures.
- Salary statistics rest on 7.4% of postings with an employer-stated salary (README).
- README run-count claim is stale: it says "45 consecutive daily runs (Sep 18 – Nov 1)". `data/logs/cron.log` has passing checks on 130 distinct dates from 2026-04-27 to 2026-11-08. Reconcile before quoting either.
- Power BI report not built; Slack webhook not configured; Airflow schedule paused (README).
- Containers stop when the host sleeps (README).

## Development conventions [V]
- Credentials only in `.env` (git-ignored) and `docker/.env`. Never print or copy values.
- Scripts resolve the project root from their own path, not the working directory.
- `init_db.sql` is destructive (DROP). Run only on fresh installs.
- Views are not re-created when their definitions change. `gold_layer.sql` says to DROP them first.

## Instructions for future work
- Inspect the current source before recommending changes. Source code and the database are the source of truth.
- Ask before changing schema, dropping objects, or altering the scheduler setup.
- Before quoting any figure, run `docs/metrics.sql` against the live database, as the README instructs.
- Do not claim the Power BI report, Slack alerts, or scheduled Airflow runs work unless verified.
