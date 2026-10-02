-- =====================================================================
-- GOLD LAYER  (idempotent: safe to run on every pipeline run)
-- Bronze = raw Adzuna JSON in data/raw
-- Silver = cleaned CSVs + star schema tables (jobs_fact, *_dim, bridge)
-- Gold   = analytics-ready materialized views in schema "gold"
--
-- NOTE: CREATE ... IF NOT EXISTS does NOT pick up edits to a view's
-- definition. After changing a definition, DROP that view (and any
-- view that depends on it) and re-run this file.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS ops;

-- ---------------------------------------------------------------------
-- Operational run log (one row per pipeline run) -> pipeline-health KPIs
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id       TEXT PRIMARY KEY,
    run_ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status       TEXT NOT NULL DEFAULT 'success',   -- success | failed
    failed_task  TEXT,
    raw_records  INT,
    jobs_total   INT,
    jobs_added   INT,
    companies    INT,
    skills       INT,
    skill_links  INT
);

-- ---------------------------------------------------------------------
-- gold.fct_jobs : one row per job, denormalised, with derived columns
-- (changing this definition requires DROP ... CASCADE - see src/db/migrate_salary_flag.py)
-- role_family is a heuristic title-regex classification (see 'Other' share)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.fct_jobs AS
SELECT
    j.job_pk,
    j.source_job_id,
    j.title,
    CASE
        WHEN j.title ~* 'machine learning|\yml\y|\yai\y|artificial intelligence|\ynlp\y' THEN 'ML / AI Engineer'
        WHEN j.title ~* 'data scien'                                                    THEN 'Data Scientist'
        WHEN j.title ~* 'data engineer|\yetl\y|analytics engineer|data platform|big data|data architect|data warehouse|dataops' THEN 'Data Engineer'
        WHEN j.title ~* 'business intelligence|\ybi\y|power bi|tableau|reporting analyst' THEN 'BI / Analytics'
        WHEN j.title ~* 'data analy|analytics analyst|insights analyst'                 THEN 'Data Analyst'
        WHEN j.title ~* 'business analyst|systems analyst|product analyst'              THEN 'Business Analyst'
        WHEN j.title ~* 'software|developer|full.?stack|front.?end|back.?end|programmer' THEN 'Software Engineer'
        WHEN j.title ~* 'automation|\yqa\y|test'                                        THEN 'Automation / QA'
        ELSE 'Other'
    END                                                AS role_family,
    c.company_name,
    l.location_name,
    l.state_name,
    j.created_at::date                                 AS posting_date,
    j.created_at,
    -- Business rule: salary_min/max/avg are EMPLOYER-STATED salaries only.
    -- Adzuna-estimated salaries (salary_is_predicted = TRUE) and rows with an unknown flag
    -- (loaded before the flag was captured and not yet backfilled) are NULL here.
    CASE WHEN j.salary_is_predicted IS FALSE THEN NULLIF(j.salary_min, 'NaN'::numeric) END AS salary_min,
    CASE WHEN j.salary_is_predicted IS FALSE THEN NULLIF(j.salary_max, 'NaN'::numeric) END AS salary_max,
    CASE WHEN j.salary_is_predicted IS FALSE THEN NULLIF(j.salary_avg, 'NaN'::numeric) END AS salary_avg,
    NULLIF(j.salary_avg, 'NaN'::numeric)               AS salary_est_avg,   -- any salary incl. estimates (reference only)
    CASE
        WHEN NULLIF(j.salary_avg, 'NaN'::numeric) IS NULL THEN 'none'
        WHEN j.salary_is_predicted IS FALSE               THEN 'disclosed'
        WHEN j.salary_is_predicted IS TRUE                THEN 'estimated'
        ELSE 'unknown'
    END                                                AS salary_basis,
    (j.salary_is_predicted IS FALSE AND NULLIF(j.salary_avg, 'NaN'::numeric) IS NOT NULL) AS has_salary,
    j.contract_type,
    j.contract_time,
    j.redirect_url,
    COALESCE(sk.skill_count, 0)                        AS skill_count
FROM jobs_fact j
LEFT JOIN companies_dim c ON c.company_id  = j.company_id
LEFT JOIN locations_dim l ON l.location_id = j.location_id
LEFT JOIN (
    SELECT job_pk, COUNT(*) AS skill_count
    FROM job_skills_bridge
    GROUP BY job_pk
) sk ON sk.job_pk = j.job_pk;

-- ---------------------------------------------------------------------
-- gold.fct_job_skills : job <-> skill (bridge with names + role family)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.fct_job_skills AS
SELECT b.job_pk, s.skill_name, f.role_family
FROM job_skills_bridge b
JOIN skills_dim    s ON s.skill_id = b.skill_id
JOIN gold.fct_jobs f ON f.job_pk   = b.job_pk;

-- ---------------------------------------------------------------------
-- gold.skill_demand_by_role : share of each role's jobs that want a skill
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.skill_demand_by_role AS
WITH role_totals AS (
    SELECT role_family, COUNT(*) AS role_jobs
    FROM gold.fct_jobs
    GROUP BY role_family
)
SELECT
    s.role_family,
    s.skill_name,
    COUNT(DISTINCT s.job_pk)                                                   AS job_count,
    ROUND(100.0 * COUNT(DISTINCT s.job_pk) / NULLIF(MAX(rt.role_jobs), 0), 1)  AS pct_of_role_jobs
FROM gold.fct_job_skills s
JOIN role_totals rt ON rt.role_family = s.role_family
GROUP BY s.role_family, s.skill_name;

-- ---------------------------------------------------------------------
-- gold.salary_by_state_role : salary stats (disclosed salaries only)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS gold.salary_by_state_role AS
SELECT
    state_name,
    role_family,
    COUNT(*)                                                    AS jobs,
    COUNT(*) FILTER (WHERE has_salary)                          AS jobs_with_salary,
    ROUND(AVG(salary_avg))                                      AS avg_salary,
    ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY salary_avg)
           FILTER (WHERE has_salary))::numeric)                 AS median_salary
FROM gold.fct_jobs
GROUP BY state_name, role_family;
