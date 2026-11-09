"""
fix_nan_values.py  --  ONE-TIME cleanup of pandas 'NaN' written by the old loader (safe to re-run)

The old load_to_db.py passed pandas NaN straight to PostgreSQL:
  * NUMERIC columns stored a real 'NaN' value  (breaks AVG)
  * TEXT columns stored the literal string 'NaN' (breaks "is this blank?" logic)
Missing values must be NULL. This script scans every nullable text/numeric column of
jobs_fact, reports how many 'NaN' values each holds, and sets them to NULL.

  python src/db/fix_nan_values.py --dry-run     # report only
  python src/db/fix_nan_values.py               # fix, then refresh the Gold views

NOT NULL columns (e.g. title) can't be nulled: they are reported so you can inspect them.
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gold_ops import refresh  # noqa: E402
from load_to_db import get_engine  # noqa: E402

TABLE = "jobs_fact"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    engine = get_engine()
    with engine.begin() as conn:
        cols = conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t
              AND data_type IN ('text', 'character varying', 'numeric', 'double precision', 'real')
            ORDER BY ordinal_position"""), {"t": TABLE}).all()

        total_fixed = 0
        print(f"{'column':22}{'type':18}{'NaN values':>11}  action")
        for name, dtype, nullable in cols:
            is_text = dtype in ("text", "character varying")
            cond = f"{name} = 'NaN'" if is_text else f"{name} = 'NaN'::{'numeric' if dtype == 'numeric' else 'float8'}"
            n = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE} WHERE {cond}")).scalar()
            if n == 0:
                continue
            if nullable != "YES":
                print(f"{name:22}{dtype:18}{n:>11}  NOT NULL column - inspect manually")
                continue
            if args.dry_run:
                print(f"{name:22}{dtype:18}{n:>11}  would set to NULL")
            else:
                conn.execute(text(f"UPDATE {TABLE} SET {name} = NULL WHERE {cond}"))
                print(f"{name:22}{dtype:18}{n:>11}  set to NULL")
                total_fixed += n
        if not args.dry_run:
            # empty strings are also "missing": normalise the two contract columns
            for name in ("contract_type", "contract_time"):
                n = conn.execute(text(f"UPDATE {TABLE} SET {name} = NULL WHERE {name} = ''")).rowcount
                if n:
                    print(f"{name:22}{'text':18}{n:>11}  empty string -> NULL")
                    total_fixed += n

    if args.dry_run:
        print("\nDry run - nothing written.")
        return
    print(f"\nFixed {total_fixed} values.")
    refresh()


if __name__ == "__main__":
    main()
