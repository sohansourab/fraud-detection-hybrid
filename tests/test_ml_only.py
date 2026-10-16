"""Module P4b tests for the ML-only caught analysis.

Covers:

* the 1:1 join fails loudly on a duplicate or unmatched ``record_id``;
* the calibration-status function labels each case correctly;
* ``ML_ONLY_CAUGHT`` excludes records flagged by any rule;
* the report excludes the uncalibrated domain and marks un-scored levels.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.ml_only import (  # noqa: E402
    ML_SCORES_CSV,
    MLError,
    calibration_status,
    join_scores_labels,
    ml_only_stats,
    run,
)


def test_join_assert_fires_on_duplicate_record_id() -> None:
    scores = pd.DataFrame({"record_id": ["A", "A"], "ml_flag": [1, 0]})
    labels = pd.DataFrame({
        "record_id": ["A", "B"],
        "is_fraud": [1, 0],
        "fraud_type": ["x", ""],
    })
    with pytest.raises(MLError, match="duplicate"):
        join_scores_labels(scores, labels)


def test_join_assert_fires_on_unmatched_record() -> None:
    scores = pd.DataFrame({"record_id": ["A"], "ml_flag": [1]})
    labels = pd.DataFrame({
        "record_id": ["A", "B"],
        "is_fraud": [1, 0],
        "fraud_type": ["x", ""],
    })
    with pytest.raises(MLError, match="do not match"):
        join_scores_labels(scores, labels)


def test_calibration_status_toy_cases() -> None:
    assert calibration_status(0.90, 12, 11, 0.5) == "CALIBRATED"
    assert calibration_status(0.50, 2, 1, 0.5) == "WEAK"      # too few val flags
    assert calibration_status(0.60, 12, 2, 0.5) == "WEAK"     # too few val TP
    assert calibration_status(0.25, 8, 2, 0.5) == "UNCALIBRATED"
    assert calibration_status(None, 0, 0, 0.5) == "UNCALIBRATED"


def test_ml_only_caught_excludes_rule_flagged() -> None:
    frame = pd.DataFrame({
        "record_id": ["A", "B", "C", "D", "E"],
        "ml_flag": [1, 1, 1, 0, 1],
        "is_fraud": [1, 1, 1, 1, 1],
        "fraud_type": ["t", "t", "t", "t", "t"],
    })
    # B is fraud + ML-flagged + rule-flagged -> must NOT count as ML-only.
    stats = ml_only_stats(frame, {"B"})
    assert stats == {
        "ml_flags": 4,
        "rule_flags": 1,
        "ml_only_flags": 3,
        "ml_only_caught": 3,
    }


def test_report_structure_and_exclusions() -> None:
    if not ML_SCORES_CSV.is_file():
        pytest.skip("reports/ml_scores.csv not generated in this checkout")

    payload = run(write=False)
    level = payload["levels"]["0.02"]
    assert level["evaluation_status"] == "in-sample"

    domains = {d["domain"]: d for d in level["domains"]}
    excluded = {d["domain"]: d for d in level["excluded"]}

    # Every domain is reported exactly once, split by calibration status.
    assert set(domains) | set(excluded) == {
        "Civil Registry", "MGNREGA Labor", "PM-JAY Medical",
    }
    assert not (set(domains) & set(excluded))
    for domain in domains.values():
        assert domain["calibration_status"] in ("CALIBRATED", "WEAK")
        assert domain["evaluation_status"] == "in-sample"
        for row in domain["by_fraud_type"]:
            assert row["evaluation_status"] in ("in-sample", "not evaluable")
    for domain in excluded.values():
        assert domain["calibration_status"] == "UNCALIBRATED"
        assert domain["note"] == "excluded: no calibrated threshold"

    for name in ("0.05", "0.10"):
        assert payload["levels"][name]["evaluation_status"] == "not evaluable"
