import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
import pandas as pd

# NOTE: This script must live at project/src/transform/clean_transform.py
# parents[2] resolves two levels up to the project root.
BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------
# Skills list — extend anytime
# "r programming" used instead of bare "r" to avoid false matches
# on words like "for", "your", "other" after lowercasing.
# ----------------------------
SKILLS = [
    # Languages
    "python", "sql", "r programming", "scala", "java", "bash",
    # Spreadsheet / BI
    "excel", "tableau", "power bi", "looker", "power query",
    # Cloud platforms
    "aws", "azure", "gcp", "bigquery", "redshift",
    # Big data / pipeline
    "spark", "pyspark", "hadoop", "airflow", "kafka", "etl", "dbt",
    # Containers / infra
    "docker", "kubernetes", "terraform", "linux", "git",
    # Python libraries
    "pandas", "numpy", "scikit-learn", "mlflow", "fastapi",
    # Databases
    "postgresql", "mysql", "mongodb", "snowflake", "databricks",
    # ML / analytics
    "machine learning", "deep learning", "nlp",
    "data analysis", "data visualization", "data engineering",
    # Legacy / stats
    "statistics", "sas",
]


# ----------------------------
# Helpers
# ----------------------------
def newest_raw_file() -> Path:
    """
    Return the most recently created raw JSON file based on filename.
    Filenames are timestamped (e.g. adzuna_4_roles_united_states_20250427_080000.json)
    so alphabetical descending == chronological descending.
    This is more reliable than st_mtime which changes on file copy/touch.
    """
    files = sorted(RAW_DIR.glob("*.json"), reverse=True)
    if not files:
        raise FileNotFoundError("No raw JSON files found in data/raw/")
    return files[0]


def clean_text(s: str) -> str:
    """Collapse whitespace and strip edges. Returns empty string for non-strings."""
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s).strip()


def extract_skills(description: str) -> list[str]:
    """
    Match skills from SKILLS list against a job description.
    Uses word-boundary-style lookbehind/lookahead to avoid partial matches.
    """
    text = clean_text(description).lower()
    found = []
    for skill in SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            found.append(skill)
    return sorted(set(found))


def safe_get(d, path, default=None):
    """Safely traverse a nested dict. path = list of keys e.g. ['company', 'display_name']"""
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def compute_hash(title: str, company: str, location: str, created_at: str) -> str:
    """SHA-256 hash of key fields — used as dedup fallback when source_job_id is missing."""
    base = f"{title}|{company}|{location}|{created_at}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


# ----------------------------
# Main
# ----------------------------
def main():
    raw_path = newest_raw_file()
    print(f"Using raw file: {raw_path.name}")

    data = json.loads(raw_path.read_text(encoding="utf-8"))

    rows: list[dict] = []
    job_skills_rows: list[dict] = []

    for job in data:
        source_job_id = str(job.get("id")) if job.get("id") is not None else None

        title   = clean_text(job.get("title", ""))
        company = clean_text(safe_get(job, ["company", "display_name"], "")) or "Unknown"

        location_display = clean_text(safe_get(job, ["location", "display_name"], "")) or "Unknown"
        location_area    = job.get("location", {}).get("area", []) if isinstance(job.get("location"), dict) else []

        # For Adzuna US data, area often looks like:
        # ["United States", "California", "Los Angeles County", "Los Angeles"]
        state_name = "Unknown"
        if isinstance(location_area, list) and len(location_area) >= 2:
            state_name = clean_text(location_area[1]) or "Unknown"

        description = clean_text(job.get("description", ""))

        # Parse created_at from ISO 8601
        created_raw = job.get("created")
        created_at = None
        if created_raw:
            try:
                created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except Exception:
                created_at = None

        # Salary fields
        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")
        # NOTE: salary_is_predicted is a boolean flag from Adzuna — not a salary value.
        # We compute salary_avg ourselves from min/max below.
        sal_avg = None
        try:
            if salary_min is not None and salary_max is not None:
                sal_avg = (float(salary_min) + float(salary_max)) / 2
            elif salary_min is not None:
                sal_avg = float(salary_min)
            elif salary_max is not None:
                sal_avg = float(salary_max)
        except Exception:
            sal_avg = None

        contract_type = clean_text(job.get("contract_type", ""))
        contract_time = clean_text(job.get("contract_time", ""))
        redirect_url  = clean_text(job.get("redirect_url", ""))

        raw_hash = compute_hash(title, company, location_display, created_raw or "")

        rows.append({
            "source":        "adzuna",
            "source_job_id": source_job_id,
            "title":         title,
            "company_name":  company,
            "location_name": location_display,
            "state_name":    state_name,
            "created_at":    created_at,
            "salary_min":    salary_min,
            "salary_max":    salary_max,
            "salary_avg":    sal_avg,       # correctly computed average, not the boolean flag
            "contract_type": contract_type,
            "contract_time": contract_time,
            "redirect_url":  redirect_url,
            "description":   description,
            "raw_hash":      raw_hash,
        })

        # Extract and store skill associations
        skills = extract_skills(description)
        for sk in skills:
            job_skills_rows.append({
                "source_job_id": source_job_id,
                "raw_hash":      raw_hash,
                "skill_name":    sk,
            })

    df_jobs = pd.DataFrame(rows)

    # Deduplicate: prefer source_job_id when present, fall back to raw_hash
    df_jobs["dedup_key"] = df_jobs["source_job_id"].fillna(df_jobs["raw_hash"])
    before = len(df_jobs)
    df_jobs = df_jobs.drop_duplicates(subset=["dedup_key"], keep="first").drop(columns=["dedup_key"])
    after = len(df_jobs)
    print(f"Deduplicated jobs: {before} -> {after}")

    df_job_skills = pd.DataFrame(job_skills_rows)
    if not df_job_skills.empty:
        # Keep only skills linked to jobs that survived dedup
        keep_hashes = set(df_jobs["raw_hash"].tolist())
        df_job_skills = df_job_skills[df_job_skills["raw_hash"].isin(keep_hashes)]
        df_job_skills = df_job_skills.drop_duplicates(subset=["raw_hash", "skill_name"])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    jobs_out   = PROCESSED_DIR / f"jobs_clean_{ts}.csv"
    skills_out = PROCESSED_DIR / f"job_skills_{ts}.csv"

    df_jobs.to_csv(jobs_out, index=False)
    df_job_skills.to_csv(skills_out, index=False)

    print(f"Saved: {jobs_out}")
    print(f"Saved: {skills_out}")


if __name__ == "__main__":
    main()
    