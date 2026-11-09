import os
import re
import shutil
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

sys.path.insert(0, str(BASE_DIR / "src"))
import run_guard  # noqa: E402  (stdlib only; stops this run overlapping the Airflow DAG)

# ----------------------------
# Scripts to run in order
# ----------------------------
SCRIPTS = [
    BASE_DIR / "src" / "ingestion" / "fetch_jobs.py",
    BASE_DIR / "src" / "transform" / "clean_transform.py",
    BASE_DIR / "src" / "db"        / "load_to_db.py",
    BASE_DIR / "src" / "db"        / "quality_checks.py",
]

# After the four steps above succeed: refresh the Gold views and write this run to
# ops.pipeline_runs (so the Excel scorecard's "Pipeline health" reflects real runs).
GOLD_OPS = BASE_DIR / "src" / "db" / "gold_ops.py"


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
def run_script(script: Path, args: list[str] | None = None) -> tuple[bool, str]:
    """
    Run a single script using the same Python interpreter as this process.
    Returns (success, stdout). Streams stdout and stderr to the pipeline log.
    """
    log(f"▶ Starting: {script.name}")

    if not script.exists():
        log(f"  ERROR: Script not found at {script}")
        return False, ""

    result = subprocess.run(
        [sys.executable, str(script), *(args or [])],
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
        return False, result.stdout

    log(f"  ✅ Finished: {script.name}")
    return True, result.stdout


def keep_awake() -> None:
    """
    macOS: stop the Mac sleeping while this run is alive. ingestion.log shows single API requests
    stalling for 15-60 minutes with no error, which is what a sleeping laptop looks like; this is
    what made some runs take 1-4 hours instead of a few minutes.  caffeinate exits by itself when
    this process does (-w). -i = no idle sleep, -s = no system sleep while on AC power (closing the
    lid on battery still sleeps the Mac; that case is detected and logged by fetch_jobs.py).
    """
    if sys.platform != "darwin" or not shutil.which("caffeinate"):
        return
    try:
        subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("Keeping the Mac awake for this run (caffeinate).")
    except OSError as e:
        log(f"  WARNING: could not start caffeinate: {e}")


def abort(run_id: str, failed_task: str) -> None:
    """Record the failed run (best effort), then exit non-zero so launchd sees the failure."""
    run_script(GOLD_OPS, ["log-failure", "--run-id", run_id, "--failed-task", failed_task])
    separator("=")
    log("PIPELINE ABORTED — fix the error above and re-run.")
    separator("=")
    sys.exit(1)  # non-zero exit so cron / Task Scheduler detects failure


def main():
    separator("=")
    log("PIPELINE RUN STARTED")
    separator("=")

    # Never run alongside another run_pipeline.py or an active Airflow DAG run (see src/run_guard.py).
    try:
        lock = run_guard.acquire_pipeline_lock()      # held until this process exits
    except run_guard.RunInProgress as e:
        log(f"Not starting: {e}.")
        sys.exit(1)
    if run_guard.airflow_marker_active():
        log("Not starting: an Airflow DAG run is in progress (data/.airflow_run.marker is recent).")
        sys.exit(1)
    keep_awake()

    start = datetime.now()
    run_id = "launchd__" + start.strftime("%Y%m%dT%H%M%S")
    raw_records = None
    api_args: list[str] = []

    for script in SCRIPTS:
        separator()
        success, out = run_script(script)
        if script.name == "fetch_jobs.py":
            m = re.search(r"Total jobs saved: (\d+)", out)
            raw_records = m.group(1) if m else None
            mc = re.search(r"API metrics: calls=(\d+) retries=(\d+) failures=(\d+)", out)
            if mc:
                api_args = ["--api-calls", mc.group(1), "--api-retries", mc.group(2), "--api-failures", mc.group(3)]
        if not success:
            abort(run_id, script.name)

    # Gold refresh is part of the run: if it fails the run is failed (Gold would be stale).
    separator()
    success, _ = run_script(GOLD_OPS, ["refresh"])
    if not success:
        abort(run_id, "gold_refresh")

    separator()
    args = ["log-success", "--run-id", run_id]
    if raw_records:
        args += ["--raw-records", raw_records]
    args += api_args
    success, _ = run_script(GOLD_OPS, args)
    if not success:
        # Data is loaded and checked; only the run-log row is missing. Warn, don't fail the run.
        log("  WARNING: could not write this run to ops.pipeline_runs")

    elapsed = (datetime.now() - start).seconds
    separator("=")
    log(f"PIPELINE COMPLETED SUCCESSFULLY in {elapsed}s")
    separator("=")


if __name__ == "__main__":
    main()
