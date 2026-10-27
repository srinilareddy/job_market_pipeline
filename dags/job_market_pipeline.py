"""
### Job Market Analytics Pipeline

Daily ELT of live Adzuna job postings through a medallion architecture:

| Layer  | What                                   | Where                                   |
|--------|----------------------------------------|-----------------------------------------|
| Bronze | raw API JSON                           | `data/raw/*.json`                       |
| Silver | cleaned CSVs -> star schema in Postgres| `data/processed/*.csv`, `jobs_fact` ... |
| Gold   | analytics-ready materialized views     | schema `gold` (+ `ops.pipeline_runs`)   |

Consumers: Power BI (DAX) reads `gold.*`; Excel scorecard is exported to `output/excel/`.

**Failure handling** - per-task retries, validation gates between layers (a task can
"succeed" while producing nothing; the gates catch that), `max_active_runs=1` because the
scripts pick the *newest* file, and a Slack alert + `ops.pipeline_runs` row on final failure.

**Config (env vars, set on the Airflow scheduler/worker):**
`JOB_MARKET_HOME` project root, `PIPELINE_PYTHON` project-venv interpreter (has pandas/psycopg2),
`MIN_RAW_JOBS` minimum raw records (default 500). Slack: Airflow connection `slack_webhook`.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pendulum

# --- Airflow 3.x / 2.x compatibility ----------------------------------------
try:  # Airflow 3
    from airflow.sdk import DAG, TaskGroup
    from airflow.providers.standard.operators.bash import BashOperator
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:  # Airflow 2.x
    from airflow import DAG
    from airflow.operators.bash import BashOperator
    from airflow.operators.python import PythonOperator
    from airflow.utils.task_group import TaskGroup

try:  # Airflow 3: fail immediately, no retries
    from airflow.sdk.exceptions import AirflowFailException
except ImportError:  # Airflow 2.x
    from airflow.exceptions import AirflowFailException

log = logging.getLogger(__name__)

# --- Configuration ----------------------------------------------------------
PROJECT_HOME = Path(os.environ.get("JOB_MARKET_HOME", Path(__file__).resolve().parents[1]))
PYTHON = os.environ.get("PIPELINE_PYTHON", sys.executable)
SLACK_CONN_ID = "slack_webhook"
LOCAL_TZ = pendulum.timezone("America/Chicago")
MAX_RAW_AGE_MIN = 180          # newest raw file must have been written within this window
GOLD_OPS = PROJECT_HOME / "src" / "db" / "gold_ops.py"


def _script(rel: str, *args: str) -> str:
    """Shell command that runs a project script with the project's interpreter."""
    parts = [f'"{PYTHON}"', f'"{PROJECT_HOME / rel}"', *args]
    return " ".join(parts)


# --- Slack alerting ---------------------------------------------------------
def _slack(message: str) -> None:
    """Best-effort Slack post. Alerting must never mask or cause a pipeline failure."""
    try:
        from airflow.providers.slack.hooks.slack_webhook import SlackWebhookHook

        SlackWebhookHook(slack_webhook_conn_id=SLACK_CONN_ID).send(text=message)
    except Exception:  # noqa: BLE001
        log.exception("Slack notification failed (non-fatal)")


def notify_failure(context: dict) -> None:
    """Runs after a task has failed *and exhausted its retries*."""
    ti = context["task_instance"]
    run_id = context.get("run_id") or getattr(ti, "run_id", "unknown")
    exc = str(context.get("exception", ""))[:500]
    url = getattr(ti, "log_url", None)
    _slack(
        ":rotating_light: *Job Market Pipeline FAILED*\n"
        f"*Task:* `{ti.task_id}`   *Try:* {getattr(ti, 'try_number', '?')}\n"
        f"*Run:* `{run_id}`\n"
        f"*Error:* ```{exc}```" + (f"\n<{url}|View task logs>" if url else "")
    )
    try:  # record the failure for pipeline-health KPIs (Power BI / Excel)
        subprocess.run(
            [PYTHON, str(GOLD_OPS), "log-failure", "--run-id", str(run_id), "--failed-task", str(ti.task_id)],
            timeout=60, check=False,
        )
    except Exception:  # noqa: BLE001
        log.exception("Could not record failure in ops.pipeline_runs (non-fatal)")


def notify_retry(context: dict) -> None:
    ti = context["task_instance"]
    _slack(f":warning: `{ti.task_id}` failed (try {getattr(ti, 'try_number', '?')}) - retrying. "
           f"{str(context.get('exception', ''))[:200]}")


def notify_success(ti=None, **_) -> None:
    raw = ti.xcom_pull(task_ids="publish.log_run_metrics") if ti else None
    try:
        m = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        m = {}
    _slack(
        ":white_check_mark: *Job Market Pipeline succeeded*\n"
        f"Raw records: {m.get('raw_records', '?')} | New jobs: {m.get('jobs_added', '?')} | "
        f"Total jobs: {m.get('jobs_total', '?')} | Skills: {m.get('skills', '?')}"
    )


# --- Validation gates (stdlib only: these run inside Airflow's own environment) ----
def validate_raw(**_) -> int:
    """Bronze gate. fetch_jobs.py exits 0 even when it collected nothing, so verify here."""
    min_jobs = int(os.environ.get("MIN_RAW_JOBS", 500))
    files = sorted((PROJECT_HOME / "data" / "raw").glob("adzuna_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise AirflowFailException("Bronze: no raw Adzuna files found.")
    newest = files[-1]
    age_min = (time.time() - newest.stat().st_mtime) / 60
    if age_min > MAX_RAW_AGE_MIN:
        raise AirflowFailException(
            f"Bronze: newest raw file {newest.name} is {age_min:.0f} min old - this run fetched nothing new.")
    records = json.loads(newest.read_text(encoding="utf-8"))
    if len(records) < min_jobs:
        raise AirflowFailException(
            f"Bronze: only {len(records)} records (< MIN_RAW_JOBS={min_jobs}); some API pages likely failed.")
    missing_id = sum(1 for r in records if r.get("id") is None)
    log.info("Bronze OK: %s records in %s (%d without id)", len(records), newest.name, missing_id)
    return len(records)                                # -> XCom


def _csv_rows(path: Path) -> int:
    with open(path, encoding="utf-8") as f:            # clean_text() strips newlines, so 1 line = 1 row
        return max(sum(1 for _ in f) - 1, 0)


def validate_silver(**_) -> None:
    """Silver gate: both CSVs exist, are fresh, and are non-empty."""
    proc = PROJECT_HOME / "data" / "processed"
    out = {}
    for prefix in ("jobs_clean_", "job_skills_"):
        files = sorted(proc.glob(f"{prefix}*.csv"))
        if not files:
            raise AirflowFailException(f"Silver: no {prefix}*.csv found.")
        age_min = (time.time() - files[-1].stat().st_mtime) / 60
        if age_min > MAX_RAW_AGE_MIN:
            raise AirflowFailException(f"Silver: {files[-1].name} is {age_min:.0f} min old - transform produced nothing new.")
        out[prefix] = _csv_rows(files[-1])
    if out["jobs_clean_"] == 0:
        raise AirflowFailException("Silver: jobs_clean CSV has 0 rows.")
    if out["job_skills_"] == 0:
        raise AirflowFailException("Silver: job_skills CSV has 0 rows - skill extraction is broken.")
    log.info("Silver OK: %s jobs, %s job-skill links", out["jobs_clean_"], out["job_skills_"])


# --- DAG ----------------------------------------------------------------------
default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
    "on_failure_callback": notify_failure,
    "on_retry_callback": notify_retry,
}

with DAG(
    dag_id="job_market_pipeline",
    description="Adzuna API -> Bronze (JSON) -> Silver (star schema) -> Gold (marts) -> Excel / Power BI",
    schedule="0 6 * * *",                               # daily 06:00 America/Chicago
    start_date=pendulum.datetime(2026, 10, 1, tz=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,                                   # scripts pick the *newest* file: never overlap runs
    dagrun_timeout=timedelta(hours=2),
    default_args=default_args,
    tags=["adzuna", "medallion", "postgres", "powerbi"],
    doc_md=__doc__,
) as dag:

    with TaskGroup("bronze", tooltip="Ingest raw API data") as bronze:
        fetch = BashOperator(
            task_id="fetch_adzuna",
            bash_command=_script("src/ingestion/fetch_jobs.py"),
            retries=3, retry_delay=timedelta(minutes=10),
            execution_timeout=timedelta(minutes=60),     # 15 terms x 3 pages with in-script retries
        )
        check_raw = PythonOperator(task_id="validate_raw", python_callable=validate_raw, retries=0)
        fetch >> check_raw

    with TaskGroup("silver", tooltip="Clean, dedupe, extract skills") as silver:
        transform = BashOperator(task_id="clean_transform", bash_command=_script("src/transform/clean_transform.py"))
        check_silver = PythonOperator(task_id="validate_silver", python_callable=validate_silver, retries=0)
        transform >> check_silver

    with TaskGroup("gold", tooltip="Load star schema, build marts, test") as gold:
        load = BashOperator(task_id="load_postgres", bash_command=_script("src/db/load_to_db.py"))
        refresh = BashOperator(task_id="refresh_gold", bash_command=_script("src/db/gold_ops.py", "refresh"))
        quality = BashOperator(task_id="quality_checks", bash_command=_script("src/db/quality_checks.py"), retries=0)
        load >> refresh >> quality

    with TaskGroup("publish", tooltip="Excel export, run log, notification") as publish:
        export_xlsx = BashOperator(task_id="export_excel", bash_command=_script("src/export/export_excel.py"))
        log_run = BashOperator(
            task_id="log_run_metrics",
            bash_command=_script(
                "src/db/gold_ops.py", "log-success",
                '--run-id "{{ run_id }}"',
                "--raw-records \"{{ ti.xcom_pull(task_ids='bronze.validate_raw') }}\"",
            ),
        )
        notify = PythonOperator(task_id="notify_success", python_callable=notify_success, retries=0)
        export_xlsx >> log_run >> notify

    bronze >> silver >> gold >> publish
