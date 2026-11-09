"""
Skill-extraction precision audit.

Rule-based extraction can produce false positives, so any precision figure has to come from
labelling real (job, skill) pairs by hand. This script does the sampling and the arithmetic;
the labelling is yours.

  1. python src/db/skill_audit.py sample            # writes docs/skill_audit_sample.csv (100 random pairs)
  2. Open the CSV. For each row read `context` (the exact text the extractor matched, with the
     match in `matched`) and type  y  (real skill mention) or  n  (false positive) in `label`.
  3. python src/db/skill_audit.py score docs/skill_audit_sample.csv
     -> precision = y / labelled, with sample size and a 95% Wilson interval, plus which skills
        were wrong. Quote the number WITH the sample size.

`sample` is reproducible (--seed) and reads Postgres through the same .env as the pipeline.
`located=no` means the matched text could not be found again (it came from a CamelCase/acronym
candidate in another spelling); label those from the job description in the database.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "transform"))
from skill_extractor_hybrid import find_evidence, job_skill_text  # noqa: E402

DEFAULT_OUT = HERE.parents[1] / "docs" / "skill_audit_sample.csv"
FIELDS = ["job_pk", "skill", "matched", "located", "context", "label"]
YES, NO = {"y", "yes", "1", "true"}, {"n", "no", "0", "false"}


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(centre - half, 0.0), min(centre + half, 1.0))


def score_labels(rows: list[dict]) -> dict:
    """Precision from labelled rows. Rows with an empty/unknown label are skipped, not counted wrong."""
    real = wrong = 0
    wrong_skills: Counter = Counter()
    for r in rows:
        lab = (r.get("label") or "").strip().lower()
        if lab in YES:
            real += 1
        elif lab in NO:
            wrong += 1
            wrong_skills[r["skill"]] += 1
    n = real + wrong
    lo, hi = wilson_interval(real, n)
    return {"labelled": n, "real": real, "wrong": wrong, "skipped": len(rows) - n,
            "precision": (real / n) if n else None, "ci_low": lo, "ci_high": hi,
            "wrong_skills": wrong_skills}


def cmd_sample(n: int, seed: float, out: Path) -> None:
    from sqlalchemy import text
    from load_to_db import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("SELECT setseed(:s)"), {"s": seed})          # reproducible sample
        rows = conn.execute(text("""
            SELECT b.job_pk, s.skill_name, j.title, j.description
            FROM job_skills_bridge b
            JOIN skills_dim s ON s.skill_id = b.skill_id
            JOIN jobs_fact  j ON j.job_pk   = b.job_pk
            ORDER BY random() LIMIT :n"""), {"n": n}).all()

    out.parent.mkdir(parents=True, exist_ok=True)
    unlocated = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for job_pk, skill, title, desc in rows:
            ev = find_evidence(skill, job_skill_text(title, desc))
            unlocated += ev is None
            w.writerow({"job_pk": job_pk, "skill": skill,
                        "matched": ev["matched"] if ev else "",
                        "located": "yes" if ev else "no",
                        "context": ev["context"].replace("\n", " ") if ev else "",
                        "label": ""})
    print(f"Wrote {len(rows)} pairs to {out}  ({unlocated} could not be located in the text)")
    print("Fill the `label` column with y / n, then run:  python src/db/skill_audit.py score", out)


def cmd_score(path: Path) -> None:
    with open(path, newline="", encoding="utf-8") as f:
        res = score_labels(list(csv.DictReader(f)))
    if not res["labelled"]:
        raise SystemExit("No labelled rows yet: put y or n in the `label` column.")
    print(f"labelled pairs : {res['labelled']}  (skipped/blank: {res['skipped']})")
    print(f"real mentions  : {res['real']}   false positives: {res['wrong']}")
    print(f"precision      : {100 * res['precision']:.1f}%  "
          f"(95% interval {100 * res['ci_low']:.1f}% - {100 * res['ci_high']:.1f}%, n={res['labelled']})")
    if res["wrong_skills"]:
        print("false positives by skill:", ", ".join(f"{k} x{v}" for k, v in res["wrong_skills"].most_common()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sample", help="write a CSV of random (job, skill) pairs to label")
    sp.add_argument("--n", type=int, default=100)
    sp.add_argument("--seed", type=float, default=0.42, help="between -1 and 1; same seed = same sample")
    sp.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sc = sub.add_parser("score", help="compute precision from a labelled CSV")
    sc.add_argument("csv", type=Path)
    args = ap.parse_args()
    if args.cmd == "sample":
        cmd_sample(args.n, args.seed, args.out)
    else:
        cmd_score(args.csv)


if __name__ == "__main__":
    main()
