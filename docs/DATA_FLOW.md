# Data flow — Job Market Analytics Pipeline

Legend: **[V]** verified in code, **[I]** inferred, **[P]** proposed.

## Steps [V]
1. **Fetch** (`fetch_jobs.py`). For each search term, requests pages 1–3 from the Adzuna search endpoint with `results_per_page` 50. Each request retries up to 3 times, with a 10-second delay and a 1-second pause between pages. It counts calls, retries and failures. It writes all results to `data/raw/adzuna_adzuna_roles_<location>_<timestamp>.json`. With no results, it logs and exits 0 (the DAG's `validate_raw` catches this).
2. **Clean** (`clean_transform.py`). Reads the newest raw file by its filename timestamp. For each record:
   - Title, company, location and description: whitespace collapsed
   - Company missing → "Unknown"; state from `location.area[1]`, or "Unknown"
   - `created` parsed as ISO 8601
   - Salary average = mean of min and max when both exist
   - `salary_is_predicted` parsed from Adzuna's "1"/"0" flag
   - `raw_hash` = SHA-256 of title, company, location and created time
   - Skills extracted from the description
   - De-duplicate on `source_job_id`, falling back to `raw_hash`
   - Keep only skill links for surviving jobs; de-duplicate pairs
   - Write timestamped `jobs_clean_*.csv` and `job_skills_*.csv`
3. **Load** (`load_to_db.py`). Reads the newest CSVs. Adds the `salary_is_predicted` column if missing (self-healing). Upserts companies, locations and skills. Maps IDs back and inserts jobs with `ON CONFLICT DO NOTHING`. Maps (`raw_hash` → `job_pk`) and inserts bridge rows. All NaN and NaT values become NULL.
4. **Quality** (`quality_checks.py`). Counts and checks listed in ARCHITECTURE.md. Exits with an error on any failure.
5. **Gold refresh** (`gold_ops.py refresh`). Runs `gold_layer.sql` (idempotent DDL), then refreshes the four materialized views and prints row counts.
6. **Run log** (`gold_ops.py log-success`). Writes counts and API metrics to `ops.pipeline_runs`. `jobs_added` = total jobs minus the previous successful run's total.
7. **Excel** (`export_excel.py`). Builds the workbook from Gold and the run log.

## Where each figure comes from [V]
| Figure | Source |
|---|---|
| Postings, companies, skills | `docs/metrics.sql` against the database |
| Salary statistics | `gold.salary_by_state_role` using employer-stated salaries only |
| Role families | `gold.fct_jobs.role_family` (title regex) |
| Pipeline health | `ops.pipeline_runs` and `data/logs/cron.log` |

## Failure paths [V]
- Any failed step in `run_pipeline.py` writes a `failed` row with the failed step and exits 1.
- In the DAG, retries are per task. Validation gates raise `AirflowFailException` so they do not retry. Final failure triggers the Slack callback (not configured) and the failure log.
- If only the success log row fails in `run_pipeline.py`, the run is still reported as successful, with a warning.

## Lineage [V]
`Adzuna API → data/raw JSON → data/processed CSV → jobs_fact / dims / bridge → gold views → Excel and Grafana`
