import os
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
def fetch_adzuna_jobs(country: str, search_term: str, location: str,
                      results_per_page: int, pages_to_fetch: int) -> list[dict]:
    """
    Fetch job postings from Adzuna API.
    Returns a list of raw job dicts.
    Retries each page up to MAX_RETRIES times on network or HTTP errors.
    """
    app_id = require_env("ADZUNA_APP_ID")
    app_key = require_env("ADZUNA_APP_KEY")

    all_jobs: list[dict] = []

    for page in range(1, pages_to_fetch + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": search_term,
            "where": location,
            "results_per_page": results_per_page,
            # "sort_by": "date" 
        }

        log(f"Fetching page {page}/{pages_to_fetch} | what='{search_term}' | where='{location}'")

        # --- Retry loop ---
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                success = True
                break  
            except requests.RequestException as e:
                log(f"  Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    log(f"  Retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    log(f"  All {MAX_RETRIES} attempts failed for page {page}. Skipping.")
            except ValueError:
                log(f"  Could not parse JSON on page {page}. Skipping.")
                break 

        if not success:
            continue

        results = data.get("results", [])
        log(f"  Received {len(results)} jobs on page {page}.")
        all_jobs.extend(results)

        # Polite pause between pages to avoid hitting rate limits
        time.sleep(1)

    log(f"Total jobs collected for '{search_term}': {len(all_jobs)}")
    return all_jobs


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

    log("Starting Adzuna ingestion...")

    all_jobs = []

    for term in search_terms:
        jobs = fetch_adzuna_jobs(
            country=country,
            search_term=term,
            location=location,
            results_per_page=results_per_page,
            pages_to_fetch=pages_to_fetch,
        )
        all_jobs.extend(jobs)

    if not all_jobs:
        log("No jobs were collected. Check your API keys, search terms, and location.")
        return

    label = "adzuna_roles"
    save_raw_json(all_jobs, provider="adzuna", search_term=label, location=location)
    log(f"Ingestion completed successfully. Total jobs saved: {len(all_jobs)}")


if __name__ == "__main__":
    main()