# Current status — Job Market Analytics Pipeline

Legend: **[V]** verified in code or logs, **[I]** inferred, **[P]** proposed.
Last verified: 2026-11-08 from the local checkout (`upgrade/airflow-gold-excel`, clean, 21 commits, last commit "Log API call counters per run; add Grafana board; refresh README metrics").

## Component status [V]
| Component | Code present | Evidence in this review |
|---|---|---|
| Fetch (Bronze) | Yes | `cron.log` and `pipeline.log` show successful runs on 2026-11-08 (`PIPELINE COMPLETED SUCCESSFULLY in 1963s`) |
| Clean (Silver files) | Yes | 351 files in `data/processed/` |
| Load (Silver database) | Yes | Not queried in this review |
| Quality checks | Yes | Passing lines in `cron.log` on recent dates |
| Gold views and run log | Yes | Code present; not queried in this review |
| Excel scorecard | Yes | Not regenerated in this review |
| launchd schedule | Yes (per README) | Last log entry 2026-11-08 08:32 |
| Airflow DAG | Yes | Schedule paused per README; not run in this review |
| Docker stack | Yes | Not started in this review |
| Grafana board | Yes (optional) | Not started in this review |
| Power BI | No (drafts only) | — |
| Slack alerts | No (callback only) | — |

## Run history [V]
- `data/logs/cron.log` has passing quality checks on 130 distinct dates, from 2026-04-27 to 2026-11-08.
- README says "45 consecutive daily runs (Sep 18 – Nov 1, 2026)" and that the Excel scorecard is dated 2026-11-01. **The README figure does not match the log.** Treat the README as out of date.
- `data/raw/` holds 173 raw files and `data/processed/` holds 351 CSVs. Nothing in the repo prunes them. **[I]** they will keep growing.

## Test status [V]
- 15 tests in `tests/` (12 skill extractor, 3 fetch). CI runs them on push.
- Not run in this review.

## Known gaps [V]
1. Two orchestrators (launchd and Airflow) can both write to the same database.
2. The empty `skill_extractor.py` file.
3. Mismatch between the README run count and the log.
4. Two definitions of "newest raw file".
5. No automated tests for loading, quality checks or Gold SQL.

## Not verified in this review [I]
- The database contents, the figures in the README, and `docs/metrics.sql` output.
- Whether launchd and Airflow have ever overlapped.
- The Excel output.

## Suggested next steps [P]
1. Choose one orchestrator for production runs, or add a lock (for example a database advisory lock) so runs cannot overlap.
2. Delete the empty `skill_extractor.py` after confirming nothing imports it.
3. Re-run `docs/metrics.sql` and update the README figures with the date of the query.
4. Add tests for `quality_checks` and `load_to_db` using a temporary PostgreSQL database.
5. Add a retention rule for raw and processed files.
