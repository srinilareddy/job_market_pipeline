-- Drop in correct order (bridge first)
DROP TABLE IF EXISTS job_skills_bridge;
DROP TABLE IF EXISTS skills_dim;
DROP TABLE IF EXISTS jobs_fact;
DROP TABLE IF EXISTS companies_dim;
DROP TABLE IF EXISTS locations_dim;

-- Dimension tables
CREATE TABLE companies_dim (
  company_id SERIAL PRIMARY KEY,
  company_name TEXT UNIQUE NOT NULL
);

CREATE TABLE locations_dim (
  location_id SERIAL PRIMARY KEY,
  location_name TEXT NOT NULL,
  state_name TEXT NOT NULL,
  UNIQUE(location_name, state_name)
);

CREATE TABLE skills_dim (
  skill_id SERIAL PRIMARY KEY,
  skill_name TEXT UNIQUE NOT NULL
);

-- Fact table
CREATE TABLE jobs_fact (
  job_pk SERIAL PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'adzuna',
  source_job_id TEXT,                    
  title TEXT NOT NULL,
  company_id INT REFERENCES companies_dim(company_id),
  location_id INT REFERENCES locations_dim(location_id),
  created_at TIMESTAMP,
  salary_min NUMERIC,
  salary_max NUMERIC,
  salary_avg NUMERIC,
  salary_is_predicted BOOLEAN,           -- Adzuna estimate (TRUE) vs employer-stated (FALSE); NULL = unknown
  contract_type TEXT,
  contract_time TEXT,
  redirect_url TEXT,
  description TEXT,
  raw_hash TEXT,                  


  CONSTRAINT uq_source_job UNIQUE (source, source_job_id)
);

-- Bridge table for many-to-many (jobs ↔ skills)
CREATE TABLE job_skills_bridge (
  job_pk INT REFERENCES jobs_fact(job_pk) ON DELETE CASCADE,
  skill_id INT REFERENCES skills_dim(skill_id) ON DELETE CASCADE,
  PRIMARY KEY (job_pk, skill_id)
);

-- Helpful indexes
CREATE INDEX idx_jobs_created_at ON jobs_fact(created_at);
CREATE INDEX idx_jobs_company ON jobs_fact(company_id);
CREATE INDEX idx_jobs_location ON jobs_fact(location_id);