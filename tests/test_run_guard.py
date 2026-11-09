"""run_guard.py: the launchd lock and the Airflow marker. Uses temp files only."""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import run_guard  # noqa: E402


def test_second_lock_is_refused_until_first_is_released(tmp_path):
    lock = tmp_path / "x.lock"
    first = run_guard.acquire_pipeline_lock(lock)
    assert run_guard.pipeline_lock_held(lock) is True
    with pytest.raises(run_guard.RunInProgress):
        run_guard.acquire_pipeline_lock(lock)
    first.close()
    assert run_guard.pipeline_lock_held(lock) is False
    run_guard.acquire_pipeline_lock(lock).close()


def test_no_lock_file_means_not_held(tmp_path):
    assert run_guard.pipeline_lock_held(tmp_path / "missing.lock") is False


def test_airflow_marker_lifecycle_and_expiry(tmp_path):
    m = tmp_path / "m"
    assert run_guard.airflow_marker_active(m) is False
    run_guard.write_airflow_marker(m)
    assert run_guard.airflow_marker_active(m) is True
    old = time.time() - run_guard.MARKER_MAX_AGE_S - 10
    os.utime(m, (old, old))
    assert run_guard.airflow_marker_active(m) is False      # a crashed DAG run does not block forever
    run_guard.clear_airflow_marker(m)
    run_guard.clear_airflow_marker(m)                        # clearing twice is fine


# --- run_pipeline.main() honours the guard (no scripts run, nothing written to the real logs) ---
def _import_run_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(run_guard, "LOCK_PATH", tmp_path / "pipeline.lock")
    monkeypatch.setattr(run_guard, "MARKER_PATH", tmp_path / "airflow.marker")
    import run_pipeline
    monkeypatch.setattr(run_pipeline, "LOG_FILE", tmp_path / "pipeline.log")
    monkeypatch.setattr(run_pipeline, "keep_awake", lambda: None)

    def _must_not_run(*a, **k):
        raise AssertionError("a pipeline script was started while the guard should have stopped the run")
    monkeypatch.setattr(run_pipeline, "run_script", _must_not_run)
    return run_pipeline


def test_run_pipeline_refuses_to_start_while_lock_is_held(monkeypatch, tmp_path):
    rp = _import_run_pipeline(monkeypatch, tmp_path)
    holder = run_guard.acquire_pipeline_lock()
    try:
        with pytest.raises(SystemExit) as e:
            rp.main()
        assert e.value.code == 1
    finally:
        holder.close()


def test_run_pipeline_refuses_to_start_while_airflow_marker_is_recent(monkeypatch, tmp_path):
    rp = _import_run_pipeline(monkeypatch, tmp_path)
    run_guard.write_airflow_marker()
    with pytest.raises(SystemExit) as e:
        rp.main()
    assert e.value.code == 1
    assert "Airflow" in (tmp_path / "pipeline.log").read_text()
