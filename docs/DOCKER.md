# Running the pipeline in Docker

One command starts everything: PostgreSQL, Airflow (API server, scheduler, DAG processor) and a
nightly database backup. All commands below are run from the `docker/` folder.

> **Docker does not make it run while your laptop sleeps.** Containers stop when the machine
> sleeps. Run this stack on your Mac to test, then on an always-on machine (see
> [Always-on hosting](#always-on-hosting)) for unattended daily runs.

## Requirements
- Docker Desktop (macOS/Windows) or Docker Engine + Compose v2.14+ (Linux)
- 4 GB RAM available to Docker (Airflow's own guidance), ~5 GB disk
- `openssl` (preinstalled on macOS/Linux)

## First run (new, empty database)

```bash
cd docker
./make-env.sh              # creates docker/.env with random secrets; copies Adzuna keys from ../.env
nano .env                  # fill ADZUNA_APP_ID / ADZUNA_APP_KEY if the script warned they are empty
docker compose build && docker compose up -d
docker compose ps          # wait until the services show "healthy" / "running" (first build ~3-5 min)
```

Open http://localhost:8080 and log in as `admin` with the password printed by `make-env.sh`
(also in `docker/.env` as `AIRFLOW_ADMIN_PASSWORD`). The DAG `job_market_pipeline` starts
unpaused and runs on its schedule (06:00 America/Chicago).

## Bring your existing data over (do this BEFORE the first full start)

The DAG runs as soon as Airflow starts, so load your data into an empty Postgres first.

```bash
cd docker
./make-env.sh
docker compose up -d postgres          # database only; wait ~15 s

# 1) dump your current (local) database - credentials come from the project's .env
cd ..
get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]\$//"; }
H="$(get DB_HOST)"; H="${H:-127.0.0.1}"; P="$(get DB_PORT)"; P="${P:-5432}"
PGPASSWORD="$(get DB_PASSWORD)" pg_dump -Fc -h "$H" -p "$P" -U "$(get DB_USER)" "$(get DB_NAME)" -f job_market.dump
ls -lh job_market.dump           # should be more than a few KB

# 2) restore into the container's database
cd docker
PGU="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)"
docker compose exec -T postgres pg_restore --clean --if-exists --no-owner --no-acl -U "$PGU" -d job_market < ../job_market.dump

# 3) check, then start the rest
docker compose exec postgres psql -U "$PGU" -d job_market -c "select count(*) from jobs_fact;"
docker compose build && docker compose up -d
```

The restore recreates your tables, the Gold views and the run log. If `pg_restore` says the dump
has an unsupported version, your local Postgres is newer than the container's: set
`POSTGRES_VERSION=<your major version>` in `docker/.env` and recreate the database volume
(`docker compose down -v` is destructive: only do it before you have data in the container).

## Daily operations

| Task | Command (from `docker/`) |
|---|---|
| Status | `docker compose ps` |
| Follow logs | `docker compose logs -f airflow-scheduler` |
| Stop (keeps data) | `docker compose down` |
| Start again | `docker compose up -d` |
| Update code or requirements | `git pull && docker compose build && docker compose up -d` |
| Run the DAG now | UI: Trigger, or `docker compose exec airflow-scheduler airflow dags trigger job_market_pipeline` |
| Look at run history | `docker compose exec postgres psql -U pipeline -d job_market -c "select run_id,status,jobs_total,jobs_added from ops.pipeline_runs order by run_ts desc limit 10;"` |
| Latest Excel scorecard | `../output/excel/job_market_scorecard_latest.xlsx` (bind-mounted to your project folder) |

Edits to `dags/` and `src/` apply without rebuilding (the project folder is mounted into the
containers). Rebuild only when `requirements.txt` or the Dockerfile changes.

## Backups
The `backup` service writes `backups/job_market_<timestamp>.dump` every 24 hours and keeps the
newest 14. Restore with the same `pg_restore --clean --if-exists --no-owner --no-acl` command as
above. **Copy `backups/` off the machine** (a second disk, cloud storage): a backup on the same
disk dies with the disk.

## Always-on hosting

Any Linux machine that stays on works: a small VPS (4 GB RAM recommended), a home server or
mini-PC, or a Raspberry Pi 4/5 with 8 GB (the images are multi-architecture). Stopgap on a Mac:
keep it plugged in and run `caffeinate -s` in a terminal; it still sleeps with the lid closed on
battery, so it is not a real solution.

On the server:

```bash
curl -fsSL https://get.docker.com | sh            # installs Docker Engine + Compose
git clone <your-repo-url> job_market_pipeline && cd job_market_pipeline
cd docker && ./make-env.sh && nano .env           # add Adzuna keys
# optional: copy your dump to the server (scp) and restore it as in "Bring your existing data over"
docker compose build && docker compose up -d
```

Containers have `restart: unless-stopped`, and Docker starts on boot, so the stack comes back
after a reboot. Missed schedule slots are not backfilled (`catchup=False`): after downtime the
next run fetches current postings.

**Reaching the UI and the database safely.** Ports are bound to `127.0.0.1` on purpose. From your
laptop, use an SSH tunnel instead of opening ports to the internet:

```bash
ssh -L 8080:localhost:8080 -L 5433:localhost:5433 you@your-server
# then browse http://localhost:8080; point Power BI at localhost:5433
```

Only SSH (port 22) should be reachable from outside; put the firewall in front of the rest.

## Slack alerts
Create a Slack Incoming Webhook, then put the `T000/B000/XXXX` part of its URL into
`SLACK_WEBHOOK_TOKEN` in `docker/.env` and run `docker compose up -d`. A failed task
(after its retries) posts to Slack and records a `failed` row in `ops.pipeline_runs`.

## Security notes
- `docker/.env` holds every secret and is git-ignored. Never commit it or paste it into chats.
- Airflow's Simple Auth Manager is a single-user login meant for personal use. Keep it behind the
  SSH tunnel; do not expose port 8080.
- Rotating `POSTGRES_PASSWORD` in `.env` does not change the password inside an existing database.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `docker compose` complains about blank variables | `docker/.env` is missing: run `./make-env.sh`. |
| `airflow-init` fails | `docker compose logs airflow-init`. Most often the database is not ready or the password in `.env` does not match an existing `pgdata` volume. |
| DAG not listed | `docker compose logs airflow-dag-processor`; look for an import error. |
| `Missing environment variable: ADZUNA_APP_KEY` in a task log | Keys are empty in `docker/.env`; fill them and `docker compose up -d`. |
| Permission errors writing `data/` or `output/` (Linux) | `AIRFLOW_UID` in `.env` must be your user id (`id -u`, not 0); re-run `docker compose up -d`. |
| `validate_raw` fails: too few records | The gate is working. Check the fetch log; tune `MIN_RAW_JOBS` in `.env` (about 70% of a normal run). |
| Containers keep restarting | `docker compose logs --tail 50 <service>`; low memory is common: give Docker 4 GB. |
