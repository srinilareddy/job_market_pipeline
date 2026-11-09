# Implementation details — Job Market Analytics Pipeline

Legend: **[V]** verified in code, **[I]** inferred, **[P]** proposed.

## Modules [V]
| File | Key functions | Notes |
|---|---|---|
| `src/ingestion/fetch_jobs.py` | `fetch_adzuna_jobs`, `recover_failed_pages`, `save_raw_json`, `main` | Module-level `API_STATS`; retries each page, one recovery pass at the end, logs system sleep, exits 1 above `max_failed_page_pct` (default 5%) after saving; optional `sort_by` / `max_days_old` from config |
| `src/transform/clean_transform.py` | `newest_raw_file`, `clean_text`, `safe_get`, `compute_hash`, `main` | Imports `skill_extractor_hybrid` by bare module name, so the script directory must be on `sys.path` (it is, when run as a script) |
| `src/transform/skill_extractor_hybrid.py` | `HybridSkillExtractor`, `extract_skills`, `extract_job_skills`, `find_evidence`, `get_skill_extractor` | Singleton extractor; strict mode by default; jobs are extracted from title + description |
| `src/run_guard.py` | `acquire_pipeline_lock`, `pipeline_lock_held`, `write_airflow_marker` | Stops launchd and the Airflow DAG overlapping (same machine) |
| `src/db/skill_audit.py` | `sample`, `score` | Samples (job, skill) pairs with the exact matched text; computes hand-labelled precision with a 95% interval |
| `src/db/load_to_db.py` | `get_engine`, `upsert_dim`, `main` | Credentials from `.env` only |
| `src/db/quality_checks.py` | `get_engine`, `main` | Raises `SystemExit` on failed checks |
| `src/db/gold_ops.py` | `refresh`, `log_success`, `log_failure`, `main` | `log_failure` never raises (alerting path) |
| `src/db/gold_layer.sql` | — | Schemas, run-log table, four materialized views |
| `src/db/migrate_salary_flag.py`, `rebuild_skills.py`, `fix_nan_values.py` | one-time fixes | Not re-read in this review |
| `src/export/export_excel.py` | `get_engine` (reused), workbook builder | Uses xlsxwriter; writes `_latest.xlsx` copy |
| `src/run_pipeline.py` | `run_script`, `abort`, `main` | Parses "Total jobs saved" and "API metrics" from fetch output |
| `dags/job_market_pipeline.py` | `validate_raw`, `validate_silver`, `notify_failure`, `notify_success` | Airflow 2 and 3 import fallbacks |

## Configuration [V]
- `config/config.json`: country, search terms, location, results per page, pages, optional `max_days_old`.
- `.env` keys (names only): `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
- Airflow: `JOB_MARKET_HOME`, `PIPELINE_PYTHON`, `MIN_RAW_JOBS`; Slack connection `slack_webhook`.

## Skill extraction rules [V]
- Dictionary categories (see ARCHITECTURE.md).
- Ambiguous names count only after a comma, slash, parenthesis, bullet or `with`/`in`/`using`/`and`/`or`/`of`, and not when followed by words like "to" or "live" for "go".
- "Excel" must be capitalised and not followed by "in", "at", "under", "as" or "by".
- Excluded from strict mode: generic words (for example "data", "cloud", "software") and location abbreviations.
- Aliases merge spellings.

## Tests [V]
- `tests/test_skill_extractor.py`: 12 tests. Cover the "go" word, skill lists, symbol languages, statistics terms, generic phrases, company values, real short mentions, and "excel" as a verb.
- `tests/test_fetch_jobs.py`: 3 tests (not re-read in this review).
- CI (`.github/workflows/tests.yml`) runs pytest on pushes and pull requests, Python 3.12, installing only pytest, requests and python-dotenv.
- No tests for `clean_transform`, `load_to_db`, `gold_layer.sql`, or the quality checks.

## Error handling [V]
- Adzuna: retries on request and HTTP errors, skip page on parse failure, counted in API stats.
- Clean: non-string fields become empty strings; bad dates become null; bad salaries become null.
- Load: NaN and NaT converted to NULL; `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for schema self-heal.
- Quality: fails the run on the listed conditions.

## Performance notes [V]
- Fetch sleeps 1 second between pages and 10 seconds between retries. Expected run time from `pipeline.log` is about 1,963 seconds (last run, 2026-11-08, from `cron.log`).
- Loader inserts in batches with SQLAlchemy `executemany`. No benchmark in the repo.
- No index beyond the primary keys, the unique key, and indexes on `created_at`, `company_id` and `location_id`.

## Not implemented [V]
- Slack alerting (callback exists; no webhook)
- Power BI report (drafts only)
- A single orchestrator (two exist)
- Monitoring alerts (Grafana board is read-only)
