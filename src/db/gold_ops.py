"""
gold_ops.py  --  Gold-layer operations, called by the Airflow DAG (or by hand).

  python gold_ops.py refresh
      Ensure gold/ops objects exist (gold_layer.sql) and REFRESH the materialized views.

  python gold_ops.py log-success --run-id RUN --raw-records N
      Write the run's metrics to ops.pipeline_runs and print them as one JSON line
      (Airflow's BashOperator pushes the last stdout line to XCom).

  python gold_ops.py log-failure --run-id RUN --failed-task TASK
      Record a failed run (never raises: alerting must not mask the real error).
"""
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_to_db import get_engine  # noqa: E402

SQL_FILE = Path(__file__).with_name("gold_layer.sql")

# Dependency order matters: later views are built on earlier ones.
MATERIALIZED_VIEWS = [
    "gold.fct_jobs",
    "gold.fct_job_skills",
    "gold.skill_demand_by_role",
    "gold.salary_by_state_role",
]

LOG_SUCCESS_SQL = text("""
    INSERT INTO ops.pipeline_runs
        (run_id, status, failed_task, raw_records, jobs_total, jobs_added, companies, skills, skill_links)
    SELECT
        :run_id, 'success', NULL, :raw_records,
        (SELECT COUNT(*) FROM jobs_fact),
        (SELECT COUNT(*) FROM jobs_fact)
            - COALESCE((SELECT jobs_total FROM ops.pipeline_runs
                        WHERE status = 'success' AND run_id <> :run_id
                        ORDER BY run_ts DESC LIMIT 1), 0),
        (SELECT COUNT(*) FROM companies_dim),
        (SELECT COUNT(*) FROM skills_dim),
        (SELECT COUNT(*) FROM job_skills_bridge)
    ON CONFLICT (run_id) DO UPDATE SET
        run_ts = now(), status = 'success', failed_task = NULL,
        raw_records = EXCLUDED.raw_records, jobs_total = EXCLUDED.jobs_total,
        jobs_added = EXCLUDED.jobs_added, companies = EXCLUDED.companies,
        skills = EXCLUDED.skills, skill_links = EXCLUDED.skill_links
    RETURNING run_id, raw_records, jobs_total, jobs_added, companies, skills, skill_links
""")

LOG_FAILURE_SQL = text("""
    INSERT INTO ops.pipeline_runs (run_id, status, failed_task)
    VALUES (:run_id, 'failed', :failed_task)
    ON CONFLICT (run_id) DO UPDATE SET run_ts = now(), status = 'failed', failed_task = :failed_task
""")


def refresh() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(SQL_FILE.read_text(encoding="utf-8")))     # idempotent DDL
        for mv in MATERIALIZED_VIEWS:
            conn.execute(text(f"REFRESH MATERIALIZED VIEW {mv}"))
            n = conn.execute(text(f"SELECT COUNT(*) FROM {mv}")).scalar()
            print(f"refreshed {mv}: {n} rows")


def log_success(run_id: str, raw_records: int | None) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(LOG_SUCCESS_SQL, {"run_id": run_id, "raw_records": raw_records}).mappings().one()
    print(json.dumps(dict(row)))


def log_failure(run_id: str, failed_task: str) -> None:
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(LOG_FAILURE_SQL, {"run_id": run_id, "failed_task": failed_task})
        print(f"logged failure for {run_id} ({failed_task})")
    except Exception as exc:  # noqa: BLE001 - alerting path must never raise
        print(f"could not log failure: {exc}", file=sys.stderr)


def _int_or_none(v: str):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh")
    s = sub.add_parser("log-success")
    s.add_argument("--run-id", required=True)
    s.add_argument("--raw-records", default=None)
    f = sub.add_parser("log-failure")
    f.add_argument("--run-id", required=True)
    f.add_argument("--failed-task", default="unknown")
    a = ap.parse_args()

    if a.cmd == "refresh":
        refresh()
    elif a.cmd == "log-success":
        log_success(a.run_id, _int_or_none(a.raw_records))
    else:
        log_failure(a.run_id, a.failed_task)


if __name__ == "__main__":
    main()
