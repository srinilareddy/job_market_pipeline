import os
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from urllib.parse import quote_plus

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"


def newest_csv(prefix: str) -> Path:
    """
    Return the most recently created processed CSV matching the given prefix.
    Sorts by filename (alphabetical descending) since filenames are timestamped —
    this is more reliable than st_mtime which changes on file copy or touch.
    """
    files = sorted(PROCESSED_DIR.glob(f"{prefix}*.csv"), reverse=True)
    if not files:
        raise FileNotFoundError(f"No processed CSV found for prefix: {prefix}")
    return files[0]


def get_engine():
    """
    Build a SQLAlchemy engine from environment variables.
    DB_USER and DB_PASSWORD have no defaults — they must be set in .env.
    Never hardcode credentials here; this file may be committed to version control.
    """
    load_dotenv()
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "job_market")
    user = os.getenv("DB_USER")       
    pwd  = os.getenv("DB_PASSWORD")      

    if not all([name, user, pwd]):
        raise ValueError("Missing DB_NAME / DB_USER / DB_PASSWORD in .env")

    pwd_enc = quote_plus(pwd) 
    url = f"postgresql+psycopg2://{user}:{pwd_enc}@{host}:{port}/{name}"
    return create_engine(url, future=True)


def upsert_dim(conn, table: str, col: str, values: list[str]) -> None:
    """
    Insert unique values into a dimension table, ignoring conflicts.
    NOTE: table and col are interpolated via f-string — only pass
    trusted internal values here, never user input.
    """
    q = text(f"""
        INSERT INTO {table} ({col})
        SELECT v FROM (SELECT unnest(:vals) AS v) s
        ON CONFLICT ({col}) DO NOTHING
    """)
    conn.execute(q, {"vals": values})


def main():
    engine = get_engine()

    jobs_csv   = newest_csv("jobs_clean_")
    skills_csv = newest_csv("job_skills_")

    print(f"Loading jobs from:   {jobs_csv.name}")
    print(f"Loading skills from: {skills_csv.name}")

    df_jobs       = pd.read_csv(jobs_csv)
    df_job_skills = pd.read_csv(skills_csv)

    # Parse created_at safely — coerce bad values to NaT
    if "created_at" in df_jobs.columns:
        df_jobs["created_at"] = pd.to_datetime(df_jobs["created_at"], errors="coerce")

    with engine.begin() as conn:

        # --------------------------------------------------
        # 1) Upsert dimension tables
        # --------------------------------------------------
        companies = sorted(df_jobs["company_name"].fillna("Unknown").unique().tolist())
        upsert_dim(conn, "companies_dim", "company_name", companies)

        # Locations require two columns 
        location_pairs = (
            df_jobs[["location_name", "state_name"]]
            .fillna("Unknown")
            .drop_duplicates()
            .to_dict(orient="records")
        )
        conn.execute(
            text("""
                INSERT INTO locations_dim (location_name, state_name)
                VALUES (:location_name, :state_name)
                ON CONFLICT (location_name, state_name) DO NOTHING
            """),
            location_pairs,  
        )

        if not df_job_skills.empty:
            skills = sorted(df_job_skills["skill_name"].dropna().unique().tolist())
            upsert_dim(conn, "skills_dim", "skill_name", skills)

        # --------------------------------------------------
        # 2) Map dimension IDs back onto the jobs dataframe
        # --------------------------------------------------
        company_map = dict(
            conn.execute(text("SELECT company_name, company_id FROM companies_dim")).all()
        )
        location_rows = conn.execute(text(
            "SELECT location_name, state_name, location_id FROM locations_dim"
        )).all()
        location_map = {(row[0], row[1]): row[2] for row in location_rows}

        df_jobs["company_id"]  = df_jobs["company_name"].map(company_map)
        df_jobs["location_id"] = df_jobs.apply(
            lambda r: location_map.get((r["location_name"], r["state_name"])),
            axis=1,
        )

        # --------------------------------------------------
        # 3) Insert into jobs_fact (batched)
        # --------------------------------------------------
        jobs_insert = df_jobs[[
            "source", "source_job_id", "title", "company_id", "location_id",
            "created_at", "salary_min", "salary_max", "salary_avg",
            "contract_type", "contract_time", "redirect_url", "description", "raw_hash",
        ]].copy()

        insert_sql = text("""
            INSERT INTO jobs_fact
                (source, source_job_id, title, company_id, location_id, created_at,
                 salary_min, salary_max, salary_avg, contract_type, contract_time,
                 redirect_url, description, raw_hash)
            VALUES
                (:source, :source_job_id, :title, :company_id, :location_id, :created_at,
                 :salary_min, :salary_max, :salary_avg, :contract_type, :contract_time,
                 :redirect_url, :description, :raw_hash)
            ON CONFLICT (source, source_job_id) DO NOTHING
        """)

        conn.execute(insert_sql, jobs_insert.to_dict(orient="records"))

        # --------------------------------------------------
        # 4) Insert job_skills_bridge (batched)
        # --------------------------------------------------
        if not df_job_skills.empty:
            skill_map = dict(
                conn.execute(text("SELECT skill_name, skill_id FROM skills_dim")).all()
            )
            jobpk_map = dict(
                conn.execute(text("SELECT raw_hash, job_pk FROM jobs_fact")).all()
            )

            df_job_skills["skill_id"] = df_job_skills["skill_name"].map(skill_map)
            df_job_skills["job_pk"]   = df_job_skills["raw_hash"].map(jobpk_map)

            bridge = (
                df_job_skills
                .dropna(subset=["job_pk", "skill_id"])[["job_pk", "skill_id"]]
                .drop_duplicates()
            )

            bridge["job_pk"]   = bridge["job_pk"].astype(int)
            bridge["skill_id"] = bridge["skill_id"].astype(int)

            bridge_sql = text("""
                INSERT INTO job_skills_bridge (job_pk, skill_id)
                VALUES (:job_pk, :skill_id)
                ON CONFLICT DO NOTHING
            """)

            # Batched insert
            conn.execute(bridge_sql, bridge.to_dict(orient="records"))

    print("✅ Loaded clean data into PostgreSQL successfully.")


if __name__ == "__main__":
    main()