"""
Run guard: stops the two orchestrators (run_pipeline.py via launchd, and the Airflow DAG) from
running at the same time. Standard library only, so the Airflow DAG can import it too.

Both orchestrators write to the same data/raw -> data/processed -> Postgres path and every script
picks the *newest* file, so two overlapping runs can load each other's half-finished files.

  * run_pipeline.py holds an exclusive flock on data/.pipeline.lock for its whole run. The OS drops
    the lock if the process dies, so a crash can never leave a stale lock behind.
  * The DAG's first task refuses to start while that lock is held, and leaves a marker file
    (data/.airflow_run.marker) until its last task has finished; run_pipeline.py refuses to start
    while a recent marker exists. A crashed DAG run leaves a marker that expires after MARKER_MAX_AGE_S.

Limits: this works between processes on the same machine and file system. It does not cover the
Docker Compose stack if its data folder is a bind mount from a Linux VM (file locks may not cross).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:                      # Windows: no flock; the guard becomes a no-op
    fcntl = None

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LOCK_PATH = DATA_DIR / ".pipeline.lock"
MARKER_PATH = DATA_DIR / ".airflow_run.marker"
MARKER_MAX_AGE_S = 3 * 3600              # longer than the DAG's 2 h dagrun_timeout


class RunInProgress(RuntimeError):
    pass


def acquire_pipeline_lock(path: Path | None = None):
    """Take the exclusive run lock. Keep the returned file object open for the whole run."""
    path = path or LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    if fcntl is not None:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise RunInProgress("another run_pipeline.py run holds the lock")
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} started={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    fh.flush()
    return fh


def pipeline_lock_held(path: Path | None = None) -> bool:
    """True if a run_pipeline.py run currently holds the lock."""
    path = path or LOCK_PATH
    if fcntl is None or not path.exists():
        return False
    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def write_airflow_marker(path: Path | None = None) -> None:
    path = path or MARKER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"started={time.strftime('%Y-%m-%d %H:%M:%S')}\n")


def clear_airflow_marker(path: Path | None = None) -> None:
    path = path or MARKER_PATH
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def airflow_marker_active(path: Path | None = None, max_age_s: int = MARKER_MAX_AGE_S) -> bool:
    path = path or MARKER_PATH
    try:
        return (time.time() - path.stat().st_mtime) < max_age_s
    except FileNotFoundError:
        return False
