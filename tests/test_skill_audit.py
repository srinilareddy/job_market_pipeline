"""Arithmetic of the precision audit (no database)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "db"))
import skill_audit  # noqa: E402


def test_wilson_interval_known_values():
    lo, hi = skill_audit.wilson_interval(90, 100)
    assert lo == pytest.approx(0.826, abs=0.002) and hi == pytest.approx(0.945, abs=0.002)
    assert skill_audit.wilson_interval(0, 0) == (0.0, 0.0)
    assert skill_audit.wilson_interval(10, 10)[1] == 1.0


def test_score_labels_skips_blanks_and_counts_wrong_skills():
    rows = [{"skill": "sql", "label": "y"}, {"skill": "go", "label": "n"}, {"skill": "go", "label": "N"},
            {"skill": "aws", "label": "yes"}, {"skill": "r", "label": ""}, {"skill": "c", "label": "?"}]
    res = skill_audit.score_labels(rows)
    assert (res["labelled"], res["real"], res["wrong"], res["skipped"]) == (4, 2, 2, 2)
    assert res["precision"] == 0.5 and res["wrong_skills"]["go"] == 2
