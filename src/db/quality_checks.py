import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from dotenv import load_dotenv


def get_engine():
    """
    Build a SQLAlchemy engine from environment variables.
    DB_USER and DB_PASSWORD must be set in .env — no defaults.
    """
    load_dotenv()

    user = os.getenv("DB_USER")
    pwd  = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST", "127.0.0.1") 
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME")

    if not all([user, pwd, name]):
        raise ValueError("Missing DB_USER / DB_PASSWORD / DB_NAME in .env")

    pwd_enc = quote_plus(pwd) 
    url = f"postgresql+psycopg2://{user}:{pwd_enc}@{host}:{port}/{name}"
    return create_engine(url, future=True)


def main():
    engine = get_engine()

    checks = {
        # Core counts
        "Total jobs":             "SELECT COUNT(*) FROM jobs_fact;",
        "Distinct companies":     "SELECT COUNT(*) FROM companies_dim;",
        "Distinct locations":     "SELECT COUNT(*) FROM locations_dim;",
        "Distinct skills":        "SELECT COUNT(*) FROM skills_dim;",
        "Skills links":           "SELECT COUNT(*) FROM job_skills_bridge;",
        # Data quality
        "Null titles":            "SELECT COUNT(*) FROM jobs_fact WHERE title IS NULL OR title = '';",
        "Null companies":         "SELECT COUNT(*) FROM jobs_fact WHERE company_id IS NULL;",
        "Null locations":         "SELECT COUNT(*) FROM jobs_fact WHERE location_id IS NULL;",
        "Jobs with salary data":  "SELECT COUNT(*) FROM jobs_fact WHERE salary_avg IS NOT NULL;",
        "Duplicate source IDs": """
            SELECT COUNT(*) FROM (
                SELECT source, source_job_id, COUNT(*) c
                FROM jobs_fact
                WHERE source_job_id IS NOT NULL
                GROUP BY source, source_job_id
                HAVING COUNT(*) > 1
            ) t;
        """,
    }

    results = {}

    with engine.connect() as conn:
        print("---- DATA QUALITY REPORT ----")
        for label, sql in checks.items():  
            val = conn.execute(text(sql)).scalar()
            results[label] = val
            print(f"  {label}: {val}")
        print("------------------------------")

    # --------------------------------------------------
    # Failure thresholds — exits with non-zero code so
    # the pipeline log captures failures in automation.
    # --------------------------------------------------
    total_jobs  = results["Total jobs"]
    null_titles = results["Null titles"]
    duplicates  = results["Duplicate source IDs"]

    if total_jobs == 0:
        raise SystemExit("❌ Quality check FAILED: 0 jobs found in database.")
    if null_titles > 0:
        raise SystemExit(f"❌ Quality check FAILED: {null_titles} job(s) have null/empty titles.")
    if duplicates > 0:
        raise SystemExit(f"❌ Quality check FAILED: {duplicates} duplicate source ID(s) detected.")

    print("✅ All quality checks passed.")


if __name__ == "__main__":
    main()