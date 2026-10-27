# Migrating an existing deployment

Do these once, in order, on the machine that already runs the pipeline.

## 1. Clean up pandas "NaN" values (bug fix in load_to_db.py)
The old loader passed pandas `NaN` straight to PostgreSQL. NUMERIC salary columns stored a real
`NaN` (makes `AVG(salary_avg)` return `NaN`); TEXT columns such as `contract_time` stored the
literal string `'NaN'` (made a "full-time share" read 20.6% instead of 79.1%). The fixed loader
writes NULL; clean the history once:
```bash
python src/db/fix_nan_values.py --dry-run     # shows how many 'NaN' values each column holds
python src/db/fix_nan_values.py               # sets them to NULL and refreshes Gold
```
`quality_checks.py` now fails the run if any NaN (numeric or text) is found.

## 2. Capture Adzuna's estimated-salary flag and build the Gold layer (do NOT re-run init_db.sql - it DROPs your tables)
Adzuna fills in *estimated* salaries for postings that don't state one (`salary_is_predicted`).
In a sample, ~98% of salaries were estimates. This one-time script adds the column, backfills it
from the raw JSON files in `data/raw/` (keep them!), and builds/rebuilds the Gold views:
```bash
python src/db/migrate_salary_flag.py
```
It is safe to re-run. Jobs whose raw file no longer exists stay `unknown` and are excluded
from salary statistics. Afterwards, salary figures cover employer-stated salaries only.

## 3. Retire launchd
```bash
launchctl list | grep -i -E "job|pipeline"          # find your label
launchctl bootout gui/$(id -u)/<label>              # stop it
rm ~/Library/LaunchAgents/<label>.plist
```
Keep `src/run_pipeline.py` for manual one-off runs, but the DAG is now the scheduler.
Two schedulers writing to the same folders will race: confirm launchd is gone first.

## 4. Re-extract skills for historical jobs (extractor fix)
The old extractor counted ordinary words ("teams", "go", "spring"...) as skills, and those
labels stay attached to historical jobs. Every job's text is already in `jobs_fact.description`,
so you can rebuild all skill links without any raw files:
```bash
python src/db/rebuild_skills.py --dry-run    # compare before/after, writes nothing
python src/db/rebuild_skills.py              # apply (one transaction) + refresh Gold
```
Do this before quoting any skill statistic. Re-run `python src/export/export_excel.py` afterwards.
