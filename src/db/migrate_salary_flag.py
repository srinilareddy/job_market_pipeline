"""
migrate_salary_flag.py  --  ONE-TIME migration (safe to re-run)

Why: Adzuna fills in *estimated* salaries for postings that don't state one and flags them
with salary_is_predicted. The original pipeline didn't store that flag, so estimates were
counted as real salaries. This script:

  1. adds jobs_fact.salary_is_predicted (BOOLEAN) if missing
  2. backfills it for existing jobs from every raw JSON file still in data/raw/
     (Bronze is the system of record - this is why raw files are kept)
  3. drops and rebuilds the Gold materialized views (their definition changed)
  4. prints how many jobs are employer-stated / estimated / unknown

Jobs whose raw JSON was deleted stay "unknown" and are excluded from salary statistics.

Usage:  python src/db/migrate_salary_flag.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gold_ops import refresh  # noqa: E402
from load_to_db import get_engine  # noqa: E402

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
CHUNK = 5000

DROP_GOLD = text("""
    DROP MATERIALIZED VIEW IF EXISTS gold.salary_by_state_role, gold.skill_demand_by_role,
                                     gold.fct_job_skills, gold.fct_jobs CASCADE
""")

BACKFILL = text("""
    UPDATE jobs_fact j
    SET salary_is_predicted = v.flag
    FROM (SELECT unnest(CAST(:ids AS text[])) AS id, unnest(CAST(:flags AS boolean[])) AS flag) v
    WHERE j.source = 'adzuna' AND j.source_job_id = v.id AND j.salary_is_predicted IS NULL
""")


def collect_flags() -> dict[str, bool]:
    """job id -> predicted?  Oldest file first, so the newest observation wins."""
    files = sorted(RAW_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    flags: dict[str, bool] = {}
    for f in files:
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  skipping unreadable {f.name}: {exc}")
            continue
        for r in records:
            raw = r.get("salary_is_predicted")
            if r.get("id") is None or raw in (None, ""):
                continue
            flags[str(r["id"])] = str(raw).strip().lower() in ("1", "true")
    print(f"Read {len(files)} raw files -> {len(flags)} jobs with a salary_is_predicted value")
    return flags


def main() -> None:
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs_fact ADD COLUMN IF NOT EXISTS salary_is_predicted BOOLEAN"))
        conn.execute(DROP_GOLD)                         # definition changed -> rebuild below
    print("Column ensured; old Gold views dropped.")

    flags = collect_flags()
    items = list(flags.items())
    updated = 0
    with engine.begin() as conn:
        for i in range(0, len(items), CHUNK):
            part = items[i:i + CHUNK]
            res = conn.execute(BACKFILL, {"ids": [k for k, _ in part], "flags": [v for _, v in part]})
            updated += res.rowcount
    print(f"Backfilled {updated} jobs_fact rows.")

    refresh()                                           # recreate + refresh Gold (gold_layer.sql)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT salary_basis, COUNT(*) FROM gold.fct_jobs GROUP BY 1 ORDER BY 2 DESC""")).all()
    total = sum(n for _, n in rows)
    print("\nSalary basis across all jobs:")
    for basis, n in rows:
        print(f"  {basis:10} {n:>7}  ({100 * n / total:.1f}%)")
    if dict(rows).get("unknown", 0):
        print("\n'unknown' = salary present but its raw JSON file is gone; excluded from salary stats.")


if __name__ == "__main__":
    main()
