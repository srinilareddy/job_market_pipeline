# Automated Job Market Data Pipeline and Dashboard

**Author:** Srinila Pogalla 
**Stack:** Adzuna API . Python · PostgreSQL · Power BI 

---

## Overview

An end-to-end data pipeline that automatically collects live job postings from the Adzuna Job Search API, cleans and transforms the data, loads it into a structured PostgreSQL database, and visualizes hiring trends in an interactive Power BI dashboard.

The system runs on a daily schedule with no manual intervention required.

---

## Architecture

```
Adzuna REST API
      │
      ▼
fetch_jobs.py          ← Live API ingestion → data/raw/*.json
      │
      ▼
clean_transform.py     ← ETL: clean, deduplicate, extract skills → data/processed/*.csv
      │
      ▼
load_to_db.py          ← Load into PostgreSQL (fact + dimension schema)
      │
      ▼
quality_checks.py      ← Validate: null checks, dedup, counts
      │
      ▼
Power BI Dashboard     ← Connected directly to PostgreSQL
```

The pipeline is orchestrated by `run_pipeline.py` and scheduled via macOS launchd to run daily at 8 AM.

---

## Database Schema

```
companies_dim          locations_dim          skills_dim
─────────────          ─────────────          ──────────
company_id (PK)        location_id (PK)       skill_id (PK)
company_name           location_name          skill_name
                       state_name
         \                  /                     |
          \                /                      |
           ──── jobs_fact ────           job_skills_bridge
                ─────────                ─────────────────
                job_pk (PK)              job_pk (FK)
                title                    skill_id (FK)
                company_id (FK)
                location_id (FK)
                salary_min / max / avg
                contract_type / time
                created_at
                redirect_url
                description
                raw_hash
```

---

## Project Structure

```
job_market_pipeline/
├── config/
│   └── config.json              # Search terms, location, pagination settings
├── src/
│   ├── ingestion/
│   │   └── fetch_jobs.py        # Phase 1 — Adzuna API ingestion
│   ├── transform/
│   │   └── clean_transform.py   # Phase 2 — ETL and skill extraction
│   ├── db/
│   │   ├── init_db.sql          # Database schema creation
│   │   ├── load_to_db.py        # Phase 2 — Load to PostgreSQL
│   │   └── quality_checks.py   # Phase 2 — Data validation
│   └── run_pipeline.py          # Phase 4 — Master pipeline runner
├── data/
│   ├── raw/                     # Raw JSON from API (gitignored)
│   ├── processed/               # Cleaned CSVs (gitignored)
│   └── logs/                    # Execution logs (gitignored)
├── .env                         # Credentials — never commit (gitignored)
├── .env.example                 # Template for environment variables
├── .gitignore
└── requirements.txt
```

---

## Setup Instructions

### 1. Clone the repository
```bash
git clone https://github.com/your-username/job_market_pipeline.git
cd job_market_pipeline
```

### 2. Create and activate a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set up environment variables
Copy the example file and fill in your credentials:
```bash
cp .env.example .env
```
Edit `.env` with your values:
```
ADZUNA_APP_ID=your_app_id_here
ADZUNA_APP_KEY=your_app_key_here
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=job_market
DB_USER=your_db_user
DB_PASSWORD=your_db_password
```

### 5. Create the database
```bash
psql -U your_db_user -d job_market -f src/db/init_db.sql
```

### 6. Run the pipeline manually
```bash
python src/run_pipeline.py
```

---

## Automation (macOS)

The pipeline is scheduled using macOS launchd to run daily at 8 AM.

**Load the schedule:**
```bash
launchctl load ~/Library/LaunchAgents/com.srinila.jobpipeline.plist
```

**Run immediately:**
```bash
launchctl start com.srinila.jobpipeline
```

**Check the log:**
```bash
cat data/logs/cron.log
```

**Remove the schedule:**
```bash
launchctl unload ~/Library/LaunchAgents/com.srinila.jobpipeline.plist
```

---

## Configuration

Edit `config/config.json` to change search terms, location, or pagination:

```json
{
  "country": "us",
  "search_terms": ["data analyst", "data engineer", "data scientist", "business analyst"],
  "location": "United States",
  "results_per_page": 50,
  "pages_to_fetch": 2
}
```

---

## Power BI Dashboard

The Power BI dashboard connects directly to PostgreSQL and includes:

- **Role Distribution** — job counts by role category
- **Salary Trends** — average salary over time
- **Geographic Distribution** — top states by job volume
- **Company Hiring Comparison** — top hiring companies by role
- **Skill Demand** — most requested technical skills

To connect Power BI to PostgreSQL:
1. Open Power BI Desktop
2. Get Data → PostgreSQL database
3. Enter your `DB_HOST` and `DB_NAME`
4. Import all five tables: `jobs_fact`, `companies_dim`, `locations_dim`, `skills_dim`, `job_skills_bridge`

---

## Skills Extracted

The pipeline automatically detects 46 technical skills from job descriptions including:

`python` `sql` `r programming` `scala` `java` `bash` `excel` `tableau` `power bi` `looker` `aws` `azure` `gcp` `bigquery` `redshift` `spark` `pyspark` `kafka` `airflow` `dbt` `docker` `kubernetes` `terraform` `git` `pandas` `numpy` `scikit-learn` `mlflow` `postgresql` `mysql` `mongodb` `snowflake` `databricks` `machine learning` `deep learning` `nlp` `data analysis` `data visualization` `data engineering` `statistics` `sas`

---

## Data Quality Checks

After every pipeline run the following are validated automatically:

| Check | Expected |
|---|---|
| Total jobs | > 0 |
| Null titles | 0 |
| Null companies | 0 |
| Null locations | 0 |
| Duplicate source IDs | 0 |
| Distinct skills | > 0 |
| Skills links | > 0 |

If any critical check fails, the pipeline exits with a non-zero code and logs the failure.

---

## Dependencies

```
pandas==3.0.1
requests==2.32.5
SQLAlchemy==2.0.46
psycopg2-binary==2.9.11
python-dotenv==1.2.1
numpy==2.4.2
```

Full list in `requirements.txt`.

---

## Phases

| Phase | Description | Status |
|---|---|---|
| Phase 1 | API ingestion and raw storage | ✅ Complete |
| Phase 2 | ETL pipeline and PostgreSQL integration | ✅ Complete |
| Phase 3 | Power BI dashboard | ✅ Complete |
| Phase 4 | Automation and optimization | ✅ Complete |

---

## References

1. Microsoft. Power BI Documentation. https://learn.microsoft.com/en-us/power-bi/
2. Adzuna. Job Search API Documentation. https://developer.adzuna.com/
3. Databricks. Medallion Architecture. https://www.databricks.com/glossary/medallion-architecture
4. Kimball, R. & Ross, M. The Data Warehouse Toolkit, 3rd ed. Wiley, 2013.
5. OECD. Online Job Vacancy Data and Skills Demand, 2021.
