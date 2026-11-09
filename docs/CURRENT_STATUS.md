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
- The longest run of consecutive days with a passing quality check in `cron.log` is 53 days (2026-09-17 to 2026-11-08); the last failure line is dated 2026-09-16. The README's earlier "45 days (Sep 18 – Nov 1)" was correct on Nov 1 and was only out of date; it now says 53. [V] 2026-11-08
- `ops.pipeline_runs` holds 14 launchd runs (2026-10-27 onward) because run logging started that day. That table is not the source for the longer streak.
- `data/raw/` holds 173 raw files and `data/processed/` holds 351 CSVs. Nothing in the repo prunes them. **[I]** they will keep growing.

## Test status [V]
- 28 tests in `tests/` after the 2026-11-08 changes (skill extractor, fetch, run guard, audit arithmetic); all passed when run on 2026-11-08. CI runs them on push.

## Known gaps [V]
Fixed on 2026-11-08:
1. ~~Two orchestrators can overlap~~ -> `src/run_guard.py`: launchd run holds a lock, the DAG's first task refuses to start while it is held, and the DAG leaves a marker that makes `run_pipeline.py` refuse to start. Same-machine only; not tested against a live Airflow.
2. ~~Empty `skill_extractor.py`~~ -> deleted (nothing imported it).
3. ~~README run count~~ -> README updated to the verified 53 days.
4. ~~Two definitions of "newest raw file"~~ -> `validate_raw` now uses the filename timestamp like `clean_transform.py`.

Still open:
5. No automated tests for loading, quality checks or Gold SQL.
6. `raw_hash` collision risk in the skill bridge.

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
