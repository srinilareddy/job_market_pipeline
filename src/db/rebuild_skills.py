"""
rebuild_skills.py  --  re-extract skills for EVERY job already in jobs_fact (safe to re-run)

Why: the old extractor counted ordinary words ("teams", "go", "spring"...) as skills, and
those labels are still attached to historical jobs. jobs_fact.description holds each job's
text, so no raw files are needed. This script:

  1. re-runs the current extractor over every description
  2. replaces job_skills_bridge with the fresh result (in one transaction: all or nothing)
  3. upserts skills_dim and removes skills no job uses any more
  4. refreshes the Gold views and prints a before/after comparison

Usage:
  python src/db/rebuild_skills.py --dry-run     # show before/after, change nothing
  python src/db/rebuild_skills.py               # apply
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import text

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "transform"))
from gold_ops import refresh  # noqa: E402
from load_to_db import get_engine  # noqa: E402
from skill_extractor_hybrid import extract_skills  # noqa: E402

CHUNK = 5000


def current_stats(conn) -> tuple[Counter, int, int]:
    rows = conn.execute(text("""
        SELECT s.skill_name, COUNT(DISTINCT b.job_pk)
        FROM job_skills_bridge b JOIN skills_dim s ON s.skill_id = b.skill_id
        GROUP BY 1""")).all()
    jobs_with = conn.execute(text("SELECT COUNT(DISTINCT job_pk) FROM job_skills_bridge")).scalar()
    links = conn.execute(text("SELECT COUNT(*) FROM job_skills_bridge")).scalar()
    return Counter(dict(rows)), jobs_with, links


def show(label: str, counts: Counter, jobs_with: int, links: int, total_jobs: int) -> None:
    print(f"\n{label}: {links} links | {jobs_with}/{total_jobs} jobs have 1+ skill "
          f"({100 * jobs_with / max(total_jobs, 1):.1f}%) | {len(counts)} distinct skills")
    for skill, n in counts.most_common(8):
        print(f"   {skill:24}{n:>7}  ({100 * n / max(total_jobs, 1):.1f}% of jobs)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="compute and compare, write nothing")
    args = ap.parse_args()

    engine = get_engine()
    with engine.connect() as conn:
        jobs = conn.execute(text("SELECT job_pk, description FROM jobs_fact")).all()
        before, b_jobs, b_links = current_stats(conn)
    total = len(jobs)
    print(f"Re-extracting skills for {total} jobs ...")

    pairs: list[tuple[int, str]] = []
    after: Counter = Counter()
    jobs_with = 0
    for job_pk, desc in jobs:
        skills = extract_skills(desc or "")
        if skills:
            jobs_with += 1
        for sk in skills:
            pairs.append((job_pk, sk))
            after[sk] += 1

    show("BEFORE", before, b_jobs, b_links, total)
    show("AFTER ", after, jobs_with, len(pairs), total)
    dropped = sorted(set(before) - set(after))
    if dropped:
        print(f"\nSkills that no longer appear anywhere ({len(dropped)}): {', '.join(dropped[:25])}")

    if args.dry_run:
        print("\nDry run - nothing written.")
        return

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM job_skills_bridge"))
        names = sorted(after)
        if names:
            conn.execute(text("""
                INSERT INTO skills_dim (skill_name)
                SELECT unnest(CAST(:names AS text[])) ON CONFLICT (skill_name) DO NOTHING"""),
                {"names": names})
        skill_map = dict(conn.execute(text("SELECT skill_name, skill_id FROM skills_dim")).all())
        rows = [{"job_pk": j, "skill_id": skill_map[s]} for j, s in pairs]
        for i in range(0, len(rows), CHUNK):
            conn.execute(text("INSERT INTO job_skills_bridge (job_pk, skill_id) VALUES (:job_pk, :skill_id) "
                              "ON CONFLICT DO NOTHING"), rows[i:i + CHUNK])
        removed = conn.execute(text(
            "DELETE FROM skills_dim WHERE skill_id NOT IN (SELECT skill_id FROM job_skills_bridge)")).rowcount
    print(f"\nApplied. Removed {removed} unused skills from skills_dim.")
    refresh()


if __name__ == "__main__":
    main()
