import os
import sys
import json
import time
import requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]  # project root
CONFIG_PATH = BASE_DIR / "config" / "config.json"
RAW_DIR = BASE_DIR / "data" / "raw"
LOG_DIR = BASE_DIR / "data" / "logs"

RAW_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "ingestion.log"

MAX_RETRIES = 3
# Seconds to wait between retries
RETRY_DELAY = 10

# Per-run API counters. main() prints them as one "API metrics:" line, which run_pipeline.py
# stores in ops.pipeline_runs.  calls = every HTTP attempt, retries = attempts that were retried,
# failures = pages skipped after all attempts failed (or an unparseable response).
API_STATS = {"calls": 0, "retries": 0, "failures": 0}

# Pages that failed every attempt. main() makes one more pass over them at the end of the run
# (a transient Adzuna/network problem has usually cleared by then); a page that is recovered is
# taken back out of API_STATS["failures"], so "failures" = pages that are really missing.
FAILED_PAGES: list[dict] = []

# If more than this share of the planned pages is still missing after the recovery pass, the run
# exits non-zero (after saving what was collected) so it is recorded as failed, not as a quiet
# partial load. Override with "max_failed_page_pct" in config/config.json.
DEFAULT_MAX_FAILED_PAGE_PCT = 5.0

# A request whose wall-clock time exceeds its monotonic time by more than this many seconds means
# the computer was asleep while the request was in flight (the monotonic clock stops during sleep,
# so the 30 s request timeout never fires).  Evidence for the 15 min - 1 h gaps seen in ingestion.log.
SLEEP_GAP_SECONDS = 60
SLEEP_EVENTS: list[float] = []


# ----------------------------
# Helpers
# ----------------------------
def log(msg: str) -> None:
    """Print + append to log file with timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config() -> dict:
    """Load config/config.json"""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def require_env(name: str) -> str:
    """Get env var or raise a clear error. Never falls back to a default."""
    val = os.getenv(name)
    if not val:
        raise ValueError(
            f"Missing environment variable: {name}. "
            f"Make sure it is set inside your .env file and loaded correctly."
        )
    return val


# ----------------------------
# Adzuna API ingestion
# ----------------------------
def _build_params(search_term: str, location: str, results_per_page: int,
                  max_days_old: int | None, sort_by: str | None) -> dict:
    params = {
        "app_id": require_env("ADZUNA_APP_ID"),
        "app_key": require_env("ADZUNA_APP_KEY"),
        "what": search_term,
        "where": location,
        "results_per_page": results_per_page,
    }
    # Optional filters (set "sort_by" / "max_days_old" in config/config.json). Left out when unset,
    # so the default behaviour is unchanged: relevance order, any posting age.
    if sort_by:
        params["sort_by"] = sort_by
    if max_days_old:
        params["max_days_old"] = int(max_days_old)
    return params


def _request_page(url: str, params: dict, page: int, count_failure: bool = True) -> dict | None:
    """
    GET one results page with up to MAX_RETRIES attempts. Returns the parsed JSON, or None when
    every attempt failed. count_failure=False is used by the end-of-run recovery pass, which has
    already counted this page once.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        API_STATS["calls"] += 1
        wall0, mono0 = time.time(), time.monotonic()
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            _note_sleep(wall0, mono0, page)
            return data
        except requests.RequestException as e:
            _note_sleep(wall0, mono0, page)
            log(f"  Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                API_STATS["retries"] += 1
                log(f"  Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                if count_failure:
                    API_STATS["failures"] += 1
                log(f"  All {MAX_RETRIES} attempts failed for page {page}. Skipping.")
        except ValueError:
            if count_failure:
                API_STATS["failures"] += 1
            log(f"  Could not parse JSON on page {page}. Skipping.")
            return None
    return None


def _note_sleep(wall0: float, mono0: float, page: int) -> None:
    """Log when the computer slept during a request (wall clock ran ahead of the monotonic clock)."""
    gap = (time.time() - wall0) - (time.monotonic() - mono0)
    if gap > SLEEP_GAP_SECONDS:
        SLEEP_EVENTS.append(gap)
        log(f"  WARNING: system sleep detected during page {page}: ~{gap:.0f}s lost while the computer was asleep")


def fetch_adzuna_jobs(country: str, search_term: str, location: str,
                      results_per_page: int, pages_to_fetch: int,
                      max_days_old: int | None = None,
                      sort_by: str | None = None) -> list[dict]:
    """
    Fetch job postings from Adzuna API.
    Returns a list of raw job dicts.
    Retries each page up to MAX_RETRIES times on network or HTTP errors. Pages that still fail
    are remembered in FAILED_PAGES so main() can try them once more at the end of the run.
    """
    all_jobs: list[dict] = []

    for page in range(1, pages_to_fetch + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = _build_params(search_term, location, results_per_page, max_days_old, sort_by)

        log(f"Fetching page {page}/{pages_to_fetch} | what='{search_term}' | where='{location}'")

        t0 = time.monotonic()
        data = _request_page(url, params, page)
        if data is None:
            FAILED_PAGES.append({"url": url, "params": params, "page": page, "term": search_term})
            continue

        results = data.get("results", [])
        log(f"  Received {len(results)} jobs on page {page} in {time.monotonic() - t0:.1f}s.")
        all_jobs.extend(results)

        # Polite pause between pages to avoid hitting rate limits
        time.sleep(1)

    log(f"Total jobs collected for '{search_term}': {len(all_jobs)}")
    return all_jobs


def recover_failed_pages() -> list[dict]:
    """One more attempt at every page that failed during the run. Returns the jobs recovered."""
    recovered: list[dict] = []
    if not FAILED_PAGES:
        return recovered
    log(f"Recovery pass: retrying {len(FAILED_PAGES)} failed page(s)...")
    for item in list(FAILED_PAGES):
        data = _request_page(item["url"], item["params"], item["page"], count_failure=False)
        if data is None:
            log(f"  Still failing: '{item['term']}' page {item['page']}")
            continue
        results = data.get("results", [])
        recovered.extend(results)
        API_STATS["failures"] = max(API_STATS["failures"] - 1, 0)
        FAILED_PAGES.remove(item)
        log(f"  Recovered '{item['term']}' page {item['page']}: {len(results)} jobs")
        time.sleep(1)
    return recovered


def save_raw_json(records: list[dict], provider: str, search_term: str, location: str) -> Path:
    """Save raw records to data/raw as a timestamped JSON file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_term = "".join(c if c.isalnum() else "_" for c in search_term.lower())
    safe_loc  = "".join(c if c.isalnum() else "_" for c in location.lower())
    filename  = f"{provider}_{safe_term}_{safe_loc}_{ts}.json"
    out_path  = RAW_DIR / filename

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    log(f"Saved raw JSON: {out_path}")
    return out_path


def main():
    load_dotenv()

    cfg = load_config()
    country          = cfg.get("country", "us")
    search_terms     = cfg.get("search_terms", ["data analyst"])
    location         = cfg.get("location", "United States")
    results_per_page = int(cfg.get("results_per_page", 50))
    pages_to_fetch   = int(cfg.get("pages_to_fetch", 2))
    max_days_old     = cfg.get("max_days_old")  # optional, e.g. 3
    sort_by          = cfg.get("sort_by")       # optional, "date" = newest first
    max_failed_pct   = float(cfg.get("max_failed_page_pct", DEFAULT_MAX_FAILED_PAGE_PCT))

    log("Starting Adzuna ingestion...")
    log(f"Filters: sort_by={sort_by or 'relevance (default)'} | max_days_old={max_days_old or 'none'}")

    FAILED_PAGES.clear()
    SLEEP_EVENTS.clear()
    all_jobs = []

    for term in search_terms:
        jobs = fetch_adzuna_jobs(
            country=country,
            search_term=term,
            location=location,
            results_per_page=results_per_page,
            pages_to_fetch=pages_to_fetch,
            max_days_old=max_days_old,
            sort_by=sort_by,
        )
        all_jobs.extend(jobs)

    all_jobs.extend(recover_failed_pages())

    # Printed before the empty-result return below, so a total API outage is recorded too.
    log(f"API metrics: calls={API_STATS['calls']} retries={API_STATS['retries']} failures={API_STATS['failures']}")

    if SLEEP_EVENTS:
        log(f"Computer slept during {len(SLEEP_EVENTS)} request(s), ~{sum(SLEEP_EVENTS):.0f}s in total "
            f"(run_pipeline.py keeps the Mac awake with caffeinate; see docs/MONITORING.md).")

    planned_pages = max(len(search_terms) * pages_to_fetch, 1)
    failed_pct = 100.0 * API_STATS["failures"] / planned_pages

    if not all_jobs:
        log("No jobs were collected. Check your API keys, search terms, and location.")
        if API_STATS["failures"]:
            sys.exit(1)      # a total outage must not look like an empty-but-fine day
        return

    label = "adzuna_roles"
    save_raw_json(all_jobs, provider="adzuna", search_term=label, location=location)
    log(f"Ingestion completed successfully. Total jobs saved: {len(all_jobs)}")

    # Data is saved first, so a failed run still leaves the partial fetch on disk.
    if failed_pct > max_failed_pct:
        log(f"ERROR: {API_STATS['failures']}/{planned_pages} pages ({failed_pct:.1f}%) are missing after the "
            f"recovery pass - above the {max_failed_pct:.1f}% limit. Failing the run.")
        sys.exit(1)
    if API_STATS["failures"]:
        log(f"  Note: {API_STATS['failures']}/{planned_pages} pages missing ({failed_pct:.1f}%), within the "
            f"{max_failed_pct:.1f}% limit.")


if __name__ == "__main__":
    main()