import subprocess
import sys
from datetime import datetime
from pathlib import Path

# NOTE: This script must live at project/src/run_pipeline.py
# parents[1] resolves one level up to the project root.
BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR  = BASE_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "pipeline.log"

# ----------------------------
# Scripts to run in order
# ----------------------------
SCRIPTS = [
    BASE_DIR / "src" / "ingestion" / "fetch_jobs.py",
    BASE_DIR / "src" / "transform" / "clean_transform.py",
    BASE_DIR / "src" / "db"        / "load_to_db.py",
    BASE_DIR / "src" / "db"        / "quality_checks.py",
]


# ----------------------------
# Helpers
# ----------------------------
def log(msg: str) -> None:
    """Print + append to pipeline log file with timestamp."""
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def separator(char: str = "-", width: int = 50) -> None:
    log(char * width)


# ----------------------------
# Runner
# ----------------------------
def run_script(script: Path) -> bool:
    """
    Run a single script using the same Python interpreter as this process.
    Returns True on success, False on failure.
    Streams stdout and stderr to the pipeline log.
    """
    log(f"▶ Starting: {script.name}")

    if not script.exists():
        log(f"  ERROR: Script not found at {script}")
        return False

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )

    # Log any stdout output from the script
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log(f"  {line}")

    # Log any stderr output (warnings, tracebacks)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log(f"  STDERR: {line}")

    if result.returncode != 0:
        log(f"  ❌ FAILED: {script.name} exited with code {result.returncode}")
        return False

    log(f"  ✅ Finished: {script.name}")
    return True


def main():
    separator("=")
    log("PIPELINE RUN STARTED")
    separator("=")

    start = datetime.now()

    for script in SCRIPTS:
        separator()
        success = run_script(script)
        if not success:
            separator("=")
            log("PIPELINE ABORTED — fix the error above and re-run.")
            separator("=")
            sys.exit(1)  # non-zero exit so cron / Task Scheduler detects failure

    elapsed = (datetime.now() - start).seconds
    separator("=")
    log(f"PIPELINE COMPLETED SUCCESSFULLY in {elapsed}s")
    separator("=")


if __name__ == "__main__":
    main()