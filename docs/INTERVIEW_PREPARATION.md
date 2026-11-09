# Interview preparation — Job Market Analytics Pipeline

Based on the code, README and logs in this repo. Figures marked as README-reported have not been re-run.
Anything about *why* you made a decision, or how you handled a problem, is marked **[ASK YOU]**.

## 1. 30-second introduction
"I built a daily ELT pipeline that collects U.S. data and software job postings from the Adzuna API, lands the raw
JSON, cleans it, and loads a star schema into PostgreSQL. Quality checks gate each run before four Gold views are
refreshed. The same steps run from a scheduled script and from an Airflow DAG, and there is an Excel scorecard
and a run log for pipeline health."

## 2. One-minute walkthrough
1. **Source.** Adzuna, 15 search terms, 3 pages each, 50 results per page, so up to 2,250 records per run.
2. **Bronze.** Raw JSON, timestamped file names.
3. **Silver.** Cleaning and de-duplication, skill extraction from descriptions, then a star schema in Postgres (jobs, companies, locations, skills, and a bridge).
4. **Gates.** Quality checks fail the run on zero jobs, null titles, duplicate IDs, or NaN values.
5. **Gold.** Four materialised views, including salary statistics that use only employer-stated salaries.
6. **Publish.** Excel scorecard with live formulas, and a run-log table for pipeline health.

## 3. Two-minute technical explanation
The pipeline has two ways to run, and that is worth discussing honestly. A launchd job runs `run_pipeline.py` at 08:00, and an Airflow DAG at 06:00 has task groups, validation gates, retries and a Slack hook. The DAG's schedule is paused in the README, and the DAG was validated through manual runs.

Data quality is the main design focus. Each stage writes files and the loader is idempotent: `jobs_fact` has a unique key on source and source ID, and re-loads skip existing rows. Salaries are kept with a flag from Adzuna, which estimates many of them. Gold statistics use only employer-stated values, so estimates do not distort the medians.

Skill extraction is a dictionary approach with rules for ambiguous names. "Go" counts only in a list such as "Python, Go, and SQL", not in "go to market". The unit tests for these rules are the most concrete evidence of the skill-extraction work.

## 4. Architecture and data-flow questions
- **Why medallion layers?** Raw files are kept, so Silver and Gold can be rebuilt. Each layer has a clear contract.
- **Why both files and a database for Silver?** Files are the handoff between stages and the database is the query layer. **[ASK YOU]** whether you would simplify this.
- **Why materialised views for Gold?** They are rebuilt on each run and queried by Excel, Grafana and Power BI. The views are refreshed in dependency order.
- **Why a run-log table?** It answers "did the pipeline run and what did it collect?" without reading log files.
- **Why two orchestrators?** It grew from a launchd script into an Airflow DAG. The honest answer is that they now duplicate logic. Name this as a risk.

## 5. Technology and design-decision questions
- **Why Airflow?** Task retries, dependency graph, validation gates and a UI for manual runs. The README says it is "built and validated through manual runs".
- **Why a rule-based skill extractor?** It is explainable and quick. The README says counts are lower bounds and should be treated as directional.
- **Why not a trained NER model?** Not tested in the repo. Say that the dictionary approach was the chosen scope **[ASK YOU]** for your reasoning.
- **Why `ON CONFLICT DO NOTHING`?** Re-running a day must not duplicate postings.
- **Why NULL instead of NaN?** `NaN` in Postgres `NUMERIC` poisons `AVG()` and is stored as a real value. The loader converts it to NULL, and the quality check fails if NaN returns.
- **Why exclude Adzuna estimates from salary statistics?** Adzuna marks many salaries as estimates. The README says 92.6% of salary values are estimates, so including them would misstate the market.

## 6. Questions about my code and implementation
- **How does the loader map skills to jobs?** It maps `raw_hash` to `job_pk` and skill names to `skill_id`, then inserts the bridge with `ON CONFLICT DO NOTHING`. **Be ready to explain the edge case:** if two postings share a hash, the mapping keeps one. This is a known risk.
- **How does the skill extractor handle "Go"?** The ambiguity rules in `skill_extractor_hybrid.py` and the tests in `test_skill_extractor.py`.
- **How are the four Gold views ordered?** `MATERIALIZED_VIEWS` in `gold_ops.py`, because later views depend on earlier ones.
- **What does `validate_raw` check?** The newest raw file is under 180 minutes old and has at least 500 records.
- **Why does `log-success` compute `jobs_added`?** It subtracts the previous successful run's total from the current total.

## 7. Errors, edge cases, testing and debugging
- **What is tested?** 12 skill-extractor tests and 3 fetch tests, run by CI on every push. Loading, quality checks and the SQL views are not tested automatically.
- **What fails loudly?** The quality checks, the DAG gates, and the non-zero exit from `run_pipeline.py`.
- **What fails silently?** `fetch_jobs.py` exits 0 when no jobs are collected. The DAG gate catches this, but the native `run_pipeline.py` path does not run that gate.
- **A real debugging story?** The README mentions that earlier September runs failed because the database was unreachable, and that NaN values had to be fixed in the loader. **[ASK YOU]** to tell the story in your own words, including what you checked first.
- **Edge cases:** missing company or state becomes "Unknown"; about 7.3% of postings have no state, per the README.

## 8. Scalability, optimisation and performance
- **Measured:** the last logged run completed in 1,963 seconds (`pipeline.log`). Most of that is sleeps and API calls by design.
- **Scale:** about 29,000 postings in the README; the daily run adds a few hundred new ones.
- **Limits:** a single PostgreSQL instance on a laptop; containers stop when the host sleeps; raw and processed files are not pruned.
- **Possible improvements (not implemented):** parallel fetch by term, a retention policy for files, batch sizes tuned for load. Do not claim a speed-up.

## 9. Likely follow-up questions by role
**Software engineering:** How do you keep secrets out of code? (`.env`, git-ignored, read by `load_dotenv`.) How do you test the Airflow DAG? (It is validated through manual runs; there are no automated DAG tests in the repo.) What would you change first? (Pick one orchestrator.)

**Data engineering:** How do you handle late or changed postings? (Unique source ID means a changed posting is not updated; the first version stays.) Is that right? **[ASK YOU]** Why did you choose files as the Silver handoff? How would you monitor freshness? (`validate_raw` and `validate_silver` age checks; the Grafana board.)

**Analytics:** How do you define a "role family"? (A title regex; 0.6% unclassified per README but check "Other".) What does "posted in the last 90 days" measure? (The README's figure, measured on 2026-10-11.) What are the limits of skill counts? (Descriptions are truncated; the README says counts are lower bounds.)

**Machine learning:** There is no model here. Expect a question on whether skill extraction could be learned. Answer as a possible next step, with the trade-off against explainability.

## 10. Improvements to discuss (not implemented)
- One orchestrator, or a lock so runs cannot overlap
- Tests for the loader and the quality checks against a temporary database
- Deleting the empty `skill_extractor.py`
- Reconciling README figures with `metrics.sql`
- Retention for raw and processed files
- A trained or hybrid skill model, compared against the dictionary

## 11. Questions for you (personal experience) **[ASK YOU]**
1. Why did you build a second orchestrator (Airflow) when launchd was already running?
2. What did you learn from the September failures, and what did you change because of them?
3. How did you decide which skills to include in the dictionary, and how did you check accuracy?
4. Why was the salary policy (employer-stated only) important to you?
5. What did you find from the Excel scorecard or Power BI draft that surprised you?
