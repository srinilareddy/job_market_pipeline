"""API counters in fetch_jobs.py. The Adzuna API is mocked, so no network access or API keys are needed.
Run: python -m pytest tests/ -q   (from project root)"""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ingestion"))
import fetch_jobs  # noqa: E402


class FakeResponse:
    def __init__(self, ok=True, payload=None):
        self.ok, self.payload = ok, payload or {"results": [{"id": "1"}]}

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError("500 Server Error")

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test")
    monkeypatch.setattr(fetch_jobs.time, "sleep", lambda s: None)       # no waiting between pages or retries
    monkeypatch.setattr(fetch_jobs, "log", lambda msg: None)            # keep the real log file untouched
    monkeypatch.setattr(fetch_jobs, "API_STATS", {"calls": 0, "retries": 0, "failures": 0})


def _fetch(pages=3):
    return fetch_jobs.fetch_adzuna_jobs("us", "data analyst", "United States", 50, pages)


def test_all_calls_succeed(monkeypatch):
    monkeypatch.setattr(fetch_jobs.requests, "get", lambda *a, **k: FakeResponse())
    jobs = _fetch(3)
    assert len(jobs) == 3
    assert fetch_jobs.API_STATS == {"calls": 3, "retries": 0, "failures": 0}


def test_one_retry_then_success(monkeypatch):
    answers = iter([FakeResponse(ok=False), FakeResponse()])
    monkeypatch.setattr(fetch_jobs.requests, "get", lambda *a, **k: next(answers))
    jobs = _fetch(1)
    assert len(jobs) == 1
    assert fetch_jobs.API_STATS == {"calls": 2, "retries": 1, "failures": 0}


def test_page_fails_all_attempts(monkeypatch):
    monkeypatch.setattr(fetch_jobs.requests, "get", lambda *a, **k: FakeResponse(ok=False))
    jobs = _fetch(1)
    assert jobs == []
    assert fetch_jobs.API_STATS == {"calls": fetch_jobs.MAX_RETRIES,
                                    "retries": fetch_jobs.MAX_RETRIES - 1,
                                    "failures": 1}


# --- recovery pass, request filters, sleep detection ---
@pytest.fixture
def _clean_state():
    fetch_jobs.FAILED_PAGES.clear()
    fetch_jobs.SLEEP_EVENTS.clear()
    yield
    fetch_jobs.FAILED_PAGES.clear()
    fetch_jobs.SLEEP_EVENTS.clear()


def test_failed_page_is_recovered_at_end_of_run(monkeypatch, _clean_state):
    # page 1 fails all attempts, then the recovery pass succeeds
    answers = iter([FakeResponse(ok=False)] * fetch_jobs.MAX_RETRIES + [FakeResponse()])
    monkeypatch.setattr(fetch_jobs.requests, "get", lambda *a, **k: next(answers))
    assert _fetch(1) == []
    assert fetch_jobs.API_STATS["failures"] == 1 and len(fetch_jobs.FAILED_PAGES) == 1
    recovered = fetch_jobs.recover_failed_pages()
    assert len(recovered) == 1
    assert fetch_jobs.API_STATS["failures"] == 0       # recovered page is no longer a failure
    assert fetch_jobs.FAILED_PAGES == []


def test_page_still_failing_after_recovery_stays_counted_once(monkeypatch, _clean_state):
    monkeypatch.setattr(fetch_jobs.requests, "get", lambda *a, **k: FakeResponse(ok=False))
    _fetch(1)
    assert fetch_jobs.recover_failed_pages() == []
    assert fetch_jobs.API_STATS["failures"] == 1       # not double counted
    assert len(fetch_jobs.FAILED_PAGES) == 1


def test_sort_and_age_filters_are_sent_only_when_set(monkeypatch, _clean_state):
    seen = []
    monkeypatch.setattr(fetch_jobs.requests, "get",
                        lambda url, params=None, **k: seen.append(dict(params)) or FakeResponse())
    fetch_jobs.fetch_adzuna_jobs("us", "x", "United States", 50, 1)
    fetch_jobs.fetch_adzuna_jobs("us", "x", "United States", 50, 1, max_days_old=3, sort_by="date")
    assert "sort_by" not in seen[0] and "max_days_old" not in seen[0]
    assert seen[1]["sort_by"] == "date" and seen[1]["max_days_old"] == 3


def test_system_sleep_is_detected(monkeypatch, _clean_state):
    # wall clock jumps 600 s during the request while the monotonic clock advances 1 s
    wall = iter([1000.0, 1600.0, 1600.0])
    mono = iter([50.0, 51.0, 51.0])
    monkeypatch.setattr(fetch_jobs.time, "time", lambda: next(wall))
    monkeypatch.setattr(fetch_jobs.time, "monotonic", lambda: next(mono))
    monkeypatch.setattr(fetch_jobs.requests, "get", lambda *a, **k: FakeResponse())
    fetch_jobs._request_page("http://x", {}, 1)
    assert len(fetch_jobs.SLEEP_EVENTS) == 1 and fetch_jobs.SLEEP_EVENTS[0] == pytest.approx(599)


# --- main(): the run fails (after saving data) when too many pages are missing ---
def _run_main(monkeypatch, tmp_path, fail_after, max_pct):
    import json as _json
    cfg = tmp_path / "config.json"
    cfg.write_text(_json.dumps({"search_terms": ["a", "b"], "pages_to_fetch": 2, "max_failed_page_pct": max_pct}))
    monkeypatch.setattr(fetch_jobs, "CONFIG_PATH", cfg)
    monkeypatch.setattr(fetch_jobs, "RAW_DIR", tmp_path)
    monkeypatch.setattr(fetch_jobs, "load_dotenv", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return FakeResponse(ok=calls["n"] <= fail_after)       # first `fail_after` calls succeed, the rest fail
    monkeypatch.setattr(fetch_jobs.requests, "get", fake_get)
    fetch_jobs.main()


def test_main_fails_after_saving_when_too_many_pages_missing(monkeypatch, tmp_path, _clean_state):
    with pytest.raises(SystemExit) as e:
        _run_main(monkeypatch, tmp_path, fail_after=1, max_pct=5)      # 1 of 4 pages fetched, 3 lost = 75%
    assert e.value.code == 1
    assert len(list(tmp_path.glob("adzuna_*.json"))) == 1                # partial data is still on disk


def test_main_passes_when_losses_are_within_the_limit(monkeypatch, tmp_path, _clean_state):
    _run_main(monkeypatch, tmp_path, fail_after=10**6, max_pct=5)        # nothing fails
    assert len(list(tmp_path.glob("adzuna_*.json"))) == 1
