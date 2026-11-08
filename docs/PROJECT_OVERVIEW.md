# Project overview — Job Market Analytics Pipeline

Legend: **[V]** verified in code or logs, **[I]** inferred, **[P]** proposed.

## Problem [V]
Job postings are scattered and change daily. This pipeline collects U.S. data and software job postings
each day, cleans and models them, and reports on roles, skills, companies, locations and disclosed salaries.

## Users and outputs [V]
- A PostgreSQL star schema and four Gold views for analysis
- An Excel KPI scorecard (`export_excel.py`)
- A run log (`ops.pipeline_runs`) and an optional Grafana board for pipeline health
- Power BI and DAX drafts (not built)

## Data source [V]
Adzuna REST API. `config/config.json` sets 15 search terms (for example "data engineer", "ml engineer",
"software developer"), location "United States", 50 results per page, 3 pages per term. That is up to 2,250 raw
records per run before de-duplication.

## Results as reported [V — README, not re-run]
As of 2026-11-01, per the README (`docs/metrics.sql` is the source):
- 29,364 postings across 6,362 companies
- 9 role families, 0.6% unclassified
- 2,179 postings (7.4%) with an employer-stated salary; median $130,000
- 206 distinct skills; 35.4% of postings have at least one skill

These figures are dated. Re-run `docs/metrics.sql` before quoting them.

## Scope and non-goals [V]
- Adzuna data only. The README states no other sources.
- It does not submit applications or send messages. (That belongs to the separate JobPilot project, not this one.)
- Skill extraction is dictionary matching, not a trained model. The README says to treat counts as directional.

## Status
See `CURRENT_STATUS.md`.
