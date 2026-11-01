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
