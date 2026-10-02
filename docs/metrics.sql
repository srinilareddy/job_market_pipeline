-- =====================================================================
-- metrics.sql : every number in the portfolio write-up comes from here.
-- Run:  psql -h 127.0.0.1 -U <user> job_market -f docs/metrics.sql
-- Paste the output next to each claim. If you can't point to a query, don't claim it.
-- =====================================================================

\echo '=== 1. VOLUME (what the pipeline actually holds) ==='
SELECT
    COUNT(*)                         AS total_jobs,
    COUNT(DISTINCT company_name)     AS distinct_companies,
    COUNT(DISTINCT state_name)       AS distinct_states,
    MIN(posting_date)                AS earliest_posting,
    MAX(posting_date)                AS latest_posting,
    MAX(posting_date) - MIN(posting_date) + 1 AS days_spanned
FROM gold.fct_jobs;

SELECT
    (SELECT COUNT(*) FROM skills_dim)          AS distinct_skills,
    (SELECT COUNT(*) FROM job_skills_bridge)   AS job_skill_links,
    ROUND((SELECT COUNT(*) FROM job_skills_bridge)::numeric / NULLIF((SELECT COUNT(*) FROM jobs_fact), 0), 2) AS avg_skills_per_job;

\echo '=== 2. COVERAGE BY ROLE FAMILY (and how much is the "Other" bucket) ==='
SELECT role_family,
       COUNT(*)                                         AS jobs,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_jobs
FROM gold.fct_jobs
GROUP BY role_family
ORDER BY jobs DESC;

\echo '=== 3. DATA QUALITY ==='
SELECT
    ROUND(100.0 * COUNT(*) FILTER (WHERE has_salary)  / COUNT(*), 1) AS pct_with_employer_stated_salary,
    ROUND(100.0 * COUNT(*) FILTER (WHERE skill_count > 0) / COUNT(*), 1) AS pct_with_1plus_skill,
    ROUND(100.0 * COUNT(*) FILTER (WHERE role_family = 'Other') / COUNT(*), 1) AS pct_role_other,
    COUNT(*) FILTER (WHERE company_name = 'Unknown')   AS jobs_unknown_company,
    COUNT(*) FILTER (WHERE state_name = 'Unknown')     AS jobs_unknown_state
FROM gold.fct_jobs;

-- Salary: what share is employer-stated vs Adzuna-estimated? Quote ONLY the disclosed figures.
SELECT salary_basis, COUNT(*) AS jobs,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM gold.fct_jobs GROUP BY salary_basis ORDER BY jobs DESC;

-- Skill extraction only sees Adzuna's description snippet (search API truncates at ~500 chars):
SELECT ROUND(AVG(length(description))) AS avg_desc_chars, MAX(length(description)) AS max_desc_chars
FROM jobs_fact;

SELECT COUNT(*) AS nan_salary_rows_must_be_0
FROM jobs_fact WHERE salary_avg = 'NaN' OR salary_min = 'NaN' OR salary_max = 'NaN';

\echo '=== 4. PIPELINE RELIABILITY (from ops.pipeline_runs) ==='
SELECT
    COUNT(*)                                                          AS runs_logged,
    COUNT(*) FILTER (WHERE status = 'success')                        AS successful,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'success') / NULLIF(COUNT(*), 0), 1) AS success_rate_pct,
    MIN(run_ts)::date                                                 AS first_run,
    MAX(run_ts)::date                                                 AS last_run,
    ROUND(AVG(raw_records) FILTER (WHERE status = 'success'))         AS avg_raw_records_per_run,
    ROUND(AVG(jobs_added)  FILTER (WHERE status = 'success'))         AS avg_new_jobs_per_run
FROM ops.pipeline_runs;

-- Longest streak without a failure is better evidence than a bare percentage:
SELECT run_ts::date AS day, status, jobs_added FROM ops.pipeline_runs ORDER BY run_ts DESC LIMIT 14;

\echo '=== 5. SKILL EXTRACTION PRECISION AUDIT ==================================='
-- Rule-based extraction can have false positives ("Go to market" -> Go).
-- Label these 100 random (job, skill) pairs by hand: count how many are real skill
-- mentions. precision = real / 100. Report that number WITH the sample size.
SELECT s.skill_name,
       substring(j.description
                 FROM GREATEST(position(lower(s.skill_name) IN lower(j.description)) - 50, 1)
                 FOR 130) AS context_snippet
FROM gold.fct_job_skills s
JOIN jobs_fact j ON j.job_pk = s.job_pk
ORDER BY random()
LIMIT 100;

-- Highest-risk skills to audit first (short / ambiguous names):
SELECT skill_name, COUNT(*) AS jobs
FROM gold.fct_job_skills
WHERE skill_name IN ('go','r','c','swift','ruby','spring','express','teams','windows','rest','apache','storm','beam')
GROUP BY skill_name ORDER BY jobs DESC;

\echo '=== 6. TOP SKILLS (only quote after the audit above) ==='
SELECT skill_name,
       COUNT(DISTINCT job_pk) AS jobs,
       ROUND(100.0 * COUNT(DISTINCT job_pk) / (SELECT COUNT(*) FROM gold.fct_jobs), 1) AS pct_of_jobs
FROM gold.fct_job_skills
GROUP BY skill_name ORDER BY jobs DESC LIMIT 15;
