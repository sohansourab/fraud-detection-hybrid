"""Module P4b tests for the ML-only caught analysis.

Covers:

* the 1:1 join fails loudly on a duplicate or unmatched ``record_id``;
* the calibration-status function labels each case correctly;
* ``ML_ONLY_CAUGHT`` excludes records flagged by any rule;
* the report's per-domain calibration outcomes are hardcoded (P4b-rerun) and
  every domain is reported exactly once;
* ``KNOWN + UNSEEN == ML_ONLY_CAUGHT`` for every domain;
* the val split's unseen leakage is reported (P4b-rerun follow-up).
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
    NO_UNSEEN,
    PINNED_EXCLUDED_NOTE,
    calibration_status,
    join_scores_labels,
    ml_only_stats,
    run,
)

#: Hardcoded per-domain calibration outcomes (P4b-rerun).
#:
#: ``PM-JAY Medical`` moved from ``UNCALIBRATED`` (pre-P2e) to ``CALIBRATED``
#: after P2e injected the unseen patterns: the ML layer was refit on the new
#: data, so the label moved. See reports/baseline_diff.md ("P4b-rerun").
#: Do NOT edit these to match a later run - if this test fails, stop and report.
EXPECTED_CALIBRATION = {
    "Civil Registry": "WEAK",
    "MGNREGA Labor": "CALIBRATED",
    "PM-JAY Medical": "CALIBRATED",  # was UNCALIBRATED before P2e
}
EXPECTED_MAIN = {"Civil Registry", "MGNREGA Labor"}
EXPECTED_EXCLUDED = {"PM-JAY Medical"}
EXPECTED_UNSEEN_TYPES = {
    "unseen_just_under_limit",
    "unseen_weekend_cluster",
    "unseen_growing_amounts",
}

#: Unseen rows that landed in the *effective* val split (the threshold split).
#: ``ml.py`` carves val out of the simulator's train split, so these are the
#: leaked rows. Hardcoded so a data change fails loudly, not silently.
EXPECTED_VAL_UNSEEN = {
    "Civil Registry": 0,
    "MGNREGA Labor": 3,
    "PM-JAY Medical": 6,
}


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


def test_report_calibration_expectations() -> None:
    if not ML_SCORES_CSV.is_file():
        pytest.skip("reports/ml_scores.csv not generated in this checkout")

    payload = run(write=False)
    level = payload["levels"]["0.02"]
    assert level["evaluation_status"] == "in-sample"

    domains = {d["domain"]: d for d in level["domains"]}
    excluded = {d["domain"]: d for d in level["excluded"]}
    reported = {**domains, **excluded}

    # Hardcoded expected outcome per domain (not derived from the output).
    assert set(reported) == set(EXPECTED_CALIBRATION)
    for name, expected in EXPECTED_CALIBRATION.items():
        assert reported[name]["calibration_status"] == expected, name

    # Partition assertion (additional check): each domain reported exactly once.
    assert set(domains) | set(excluded) == set(EXPECTED_CALIBRATION)
    assert not (set(domains) & set(excluded))
    assert set(domains) == EXPECTED_MAIN
    assert set(excluded) == EXPECTED_EXCLUDED
    assert excluded["PM-JAY Medical"]["note"] == PINNED_EXCLUDED_NOTE

    for domain in reported.values():
        assert domain["evaluation_status"] == "in-sample"
        for row in domain["by_fraud_type"]:
            assert row["evaluation_status"] in ("in-sample", "not evaluable")

    for name in ("0.05", "0.10"):
        assert payload["levels"][name]["evaluation_status"] == "not evaluable"


def test_known_and_unseen_sum_to_ml_only_caught() -> None:
    if not ML_SCORES_CSV.is_file():
        pytest.skip("reports/ml_scores.csv not generated in this checkout")

    payload = run(write=False)
    level = payload["levels"]["0.02"]
    rows = level["domains"] + level["excluded"]
    assert rows, "no domains reported"
    for domain in rows:
        assert (
            domain["ml_only_caught_known"] + domain["ml_only_caught_unseen"]
            == domain["ml_only_caught"]
        ), domain["domain"]
        assert {r["fraud_type"] for r in domain["unseen_by_type"]} == (
            EXPECTED_UNSEEN_TYPES
        ), domain["domain"]
        for row in domain["unseen_by_type"]:
            assert row["evaluation_status"] in (
                "in-sample", "not evaluable", NO_UNSEEN,
            )
            assert row["recall_note"]

    # Civil injects no unseen typology: the row must say so, not "0 catches".
    civil = next(d for d in rows if d["domain"] == "Civil Registry")
    for row in civil["unseen_by_type"]:
        assert row["evaluation_status"] == NO_UNSEEN
        assert row["recall_note"] == "no unseen events injected for this domain"

    # MGNREGA's single catch is too thin to report as a recall estimate.
    mgnrega = next(d for d in rows if d["domain"] == "MGNREGA Labor")
    thin = next(
        r for r in mgnrega["unseen_by_type"]
        if r["fraud_type"] == "unseen_just_under_limit"
    )
    assert (thin["ml_only_caught"], thin["events"]) == (1, 12)
    assert "not evaluable as a recall estimate" in thin["recall_note"]


def test_val_leakage_is_reported() -> None:
    if not ML_SCORES_CSV.is_file():
        pytest.skip("reports/ml_scores.csv not generated in this checkout")

    payload = run(write=False)
    level = payload["levels"]["0.02"]
    target = payload["precision_target"]
    rows = level["domains"] + level["excluded"]

    for domain in rows:
        leak = domain["leakage"]
        assert leak["leaks"] == (leak["val_unseen"] > 0)
        assert leak["val_unseen"] == EXPECTED_VAL_UNSEEN[domain["domain"]], (
            domain["domain"]
        )

    # PM-JAY: 6 unseen rows sit in val; excluding them val precision falls
    # below the target, so its CALIBRATED label rests on the injected patterns.
    pmjay = next(d for d in rows if d["domain"] == "PM-JAY Medical")
    assert pmjay["leakage"]["leaks"] is True
    assert pmjay["leakage"]["val_unseen_flagged"] == pmjay["leakage"]["val_unseen"]
    assert pmjay["leakage"]["val_precision_excl_unseen"] < target

    civil = next(d for d in rows if d["domain"] == "Civil Registry")
    assert civil["leakage"]["leaks"] is False
