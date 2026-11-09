# Architecture — Job Market Analytics Pipeline

Legend: **[V]** verified in code, **[I]** inferred, **[P]** proposed.

## Medallion layers [V]
| Layer | Location | Contents |
|---|---|---|
| Bronze | `data/raw/adzuna_*.json` | Raw API records, timestamped in the file name |
| Silver (files) | `data/processed/jobs_clean_*.csv`, `job_skills_*.csv` | Cleaned rows and job-skill pairs |
| Silver (database) | PostgreSQL `public` | `jobs_fact`, `companies_dim`, `locations_dim`, `skills_dim`, `job_skills_bridge` |
| Gold | PostgreSQL schema `gold` | `fct_jobs`, `fct_job_skills`, `skill_demand_by_role`, `salary_by_state_role` (materialized views) |
| Ops | PostgreSQL schema `ops` | `pipeline_runs` |

## Two orchestrators [V]
The same steps run two ways:
1. **`src/run_pipeline.py`** runs fetch, clean, load, quality checks, Gold refresh and run log in order. It exits non-zero on any failure and logs a failed row. launchd runs it at 08:00. If the laptop is asleep, it runs on wake.
2. **`dags/job_market_pipeline.py`** is an Airflow DAG at 06:00 America/Chicago, `max_active_runs=1`. Task groups: bronze (`fetch_adzuna` → `validate_raw`), silver (`clean_transform` → `validate_silver`), gold (`load_postgres` → `refresh_gold` → `quality_checks`), publish (`export_excel` → `log_run_metrics` → `notify_success`). Its schedule is paused per the README; manual runs were validated.

The two paths differ. `run_pipeline.py` does not run the validation gates or export the Excel file. The DAG does not call `run_pipeline.py`. **[I]** This is a maintenance risk: a fix in one path can be missed in the other.

## Validation gates (DAG only) [V]
- `validate_raw`: newest `adzuna_*.json` must be under 180 minutes old and contain at least `MIN_RAW_JOBS` records (default 500).
- `validate_silver`: newest `jobs_clean_*` and `job_skills_*` must be fresh and non-empty; the skills CSV must not be empty.
- `quality_checks` (both paths): zero jobs, null titles, duplicate source IDs, literal "NaN" text, NaN salary values.

## Database design [V]
- `jobs_fact` has a unique key on (`source`, `source_job_id`). Re-loads use `ON CONFLICT DO NOTHING`.
- Dimensions: `companies_dim` (unique name), `locations_dim` (unique location + state), `skills_dim` (unique name).
- Bridge `job_skills_bridge` with composite primary key (`job_pk`, `skill_id`).
- Salary columns: `salary_is_predicted` (TRUE estimate, FALSE employer-stated, NULL unknown). Gold uses only FALSE for salary statistics.
- Gold views are rebuilt with `REFRESH MATERIALIZED VIEW` in dependency order (`MATERIALIZED_VIEWS` in `gold_ops.py`).

## Skill extraction [V]
`skill_extractor_hybrid.py` matches a dictionary of about 200 skills in categories (languages, frameworks, ML, big data, databases, cloud, DevOps, BI, version control, testing, methodology, statistics). It adds:
- Context rules for ambiguous short names ("Go", "R", "C", "Teams", "Spring", "Rest"): they count only in a list context.
- A case-sensitive rule for "Excel" (so the verb "excel" does not match).
- Aliases ("amazon web services" → "aws", "k8s" → "kubernetes").
- Candidate patterns (CamelCase, acronyms, dotted and hyphenated terms) that are kept only if they are known skills in strict mode.

## Deployment [V]
- Native: a Python venv, PostgreSQL, launchd.
- Docker (`docker/`): PostgreSQL, Airflow, a nightly backup, and an optional Grafana board bound to localhost. Containers stop when the host sleeps.
