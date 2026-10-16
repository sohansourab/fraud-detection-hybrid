"""Module P4c tests for the HYBRID combination report.

Covers:

* the selection set drops unseen val rows;
* the combination is chosen on the validation split only (test rows are refused);
* the per-domain calibration outcomes are hardcoded;
* only CALIBRATED domains enter the main table (a WEAK domain never does);
* every detector row reconciles ``flagged == TP + FP + OTHER_FRAUD``;
* the ML normalisation uses the selection rows.
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

from fraud.config import get_config  # noqa: E402
from fraud.hybrid import (  # noqa: E402
    HybridError,
    add_normalised,
    candidate_names,
    ml_norm_stats,
    run,
    selection_rows,
)

#: Hardcoded per-domain calibration outcomes (P4c). Computed on the validation
#: rows with the unseen typologies excluded and the *committed* ML thresholds.
#: Do NOT edit these to match a later run - if this test fails, stop and report.
EXPECTED_CALIBRATION = {
    "Civil Registry": "WEAK",
    "MGNREGA Labor": "CALIBRATED",
    "PM-JAY Medical": "UNCALIBRATED",  # 7 flags, 3 TP, precision 0.429
}
EXPECTED_MAIN = ["MGNREGA Labor"]
EXPECTED_EXCLUDED = {"Civil Registry", "PM-JAY Medical"}


def test_selection_rows_drop_unseen_val_rows() -> None:
    frame = pd.DataFrame({
        "record_id": ["A", "B", "C", "D"],
        "split": ["val", "val", "val", "test"],
        "is_fraud": [1, 0, 1, 1],
        "unseen": [False, False, True, True],
    })
    selected = selection_rows(frame)
    assert set(selected["record_id"]) == {"A", "B"}


def test_select_combination_refuses_test_rows() -> None:
    frame = pd.DataFrame({
        "record_id": ["A"],
        "split": ["test"],
        "is_fraud": [1],
        "unseen": [False],
    })
    with pytest.raises(HybridError, match="validation split only"):
        from fraud.hybrid import select_combination

        select_combination(frame, get_config())


def test_ml_norm_stats_and_normalisation_use_given_rows() -> None:
    frame = pd.DataFrame({
        "record_id": ["A", "B", "C"],
        "domain": ["D", "D", "D"],
        "ml_score": [0.0, 0.5, 1.0],
        "severity": [0, 0, 0],
    })
    stats = ml_norm_stats(frame)
    assert stats == {"D": (0.0, 1.0)}
    out = add_normalised(frame, stats, get_config())
    assert list(out["ml_norm"]) == [0.0, 0.5, 1.0]


def test_candidate_set_is_fixed() -> None:
    cfg = get_config()
    assert candidate_names(cfg) == [
        "rule_only", "max", "weighted_w0.3", "weighted_w0.5", "weighted_w0.7",
        "rule_first",
    ]


@pytest.fixture(scope="module")
def payload() -> dict:
    from fraud.hybrid import ML_SCORES_CSV

    if not ML_SCORES_CSV.is_file():
        pytest.skip("reports/ml_scores.csv not generated in this checkout")
    return run(write=False)


def test_calibration_expectations(payload: dict) -> None:
    reported = {
        row["domain"]: row["calibration_status"]
        for row in payload["domains"] + payload["excluded"]
    }
    assert reported == EXPECTED_CALIBRATION
    for row in payload["domains"] + payload["excluded"]:
        assert row["evaluation_status"] == "in-sample"
        assert row["leakage_note"] == payload["leakage_note"]


def test_only_calibrated_domains_in_main_table(payload: dict) -> None:
    main = [row["domain"] for row in payload["domains"]]
    excluded = {row["domain"] for row in payload["excluded"]}

    assert main == EXPECTED_MAIN
    assert excluded == EXPECTED_EXCLUDED
    assert not (set(main) & excluded)
    assert set(main) | excluded == set(EXPECTED_CALIBRATION)

    # A WEAK or UNCALIBRATED domain never appears in the main table.
    for row in payload["domains"]:
        assert row["calibration_status"] == "CALIBRATED"
    for row in payload["excluded"]:
        assert row["calibration_status"] in ("WEAK", "UNCALIBRATED")


def test_selection_is_on_val_and_reports_val_f1(payload: dict) -> None:
    selection = payload["selection"]
    names = [c["combination"] for c in selection["candidates"]]
    assert names == candidate_names(get_config())
    assert selection["selected"] in names
    assert len([c for c in selection["candidates"] if c["selected"]]) == 1
    # Rule-only wins here, so the baseline must be the selected combination.
    assert selection["no_candidate_beat_rule_only"] is True
    assert selection["selected"] == "rule_only"
    assert selection["selected_val_f1"] == selection["rule_only_val_f1"]


def test_detector_rows_reconcile(payload: dict) -> None:
    assert payload["domains"], "no CALIBRATED domain to report"
    for domain in payload["domains"]:
        assert [r["detector"] for r in domain["detectors"]] == [
            "RULES_ONLY", "ML_ONLY", "HYBRID",
        ]
        for row in domain["detectors"]:
            assert row["flags"] == row["tp"] + row["fp"] + row["other_fraud"]
            assert row["evaluation_status"] == "in-sample"
            assert row["calibration_status"] == domain["calibration_status"]
            assert row["selection_rows_used"] == domain["selection_rows_used"]
        split = domain["hybrid_recall_split"]
        hybrid = next(r for r in domain["detectors"] if r["detector"] == "HYBRID")
        assert split["known_caught"] == hybrid["tp"]
        assert split["unseen_caught"] == hybrid["other_fraud"]


def test_selection_set_has_no_room(payload: dict) -> None:
    # Check 1: the rules are perfect on the selection rows, so the candidate
    # comparison cannot distinguish them. This must be stated, not implied.
    selection = payload["selection"]
    assert selection["selection_set_has_room"] is False
    assert selection["rule_only_val_fp"] == 0
    assert selection["rule_only_val_fn"] == 0


def test_unseen_recall_is_not_evaluable(payload: dict) -> None:
    # Check 2 (part): 4 unseen events is too few for a recall estimate.
    for domain in payload["domains"]:
        split = domain["hybrid_recall_split"]
        if split["unseen_fraud"] < 10:
            assert split["unseen_evaluation_status"] == "not evaluable"
            assert split["unseen_note"]


def test_cross_rule_overlap_is_reported(payload: dict) -> None:
    # Check 2: the aggregate OTHER_FRAUD is 0, but the rule cross-rule overlap is
    # not. Both must be visible so the zero is not read as a filter artefact.
    domain = payload["domains"][0]
    rows = {r["detector"]: r for r in domain["detectors"]}
    assert rows["RULES_ONLY"]["cross_rule_overlap"] == 3
    assert rows["HYBRID"]["cross_rule_overlap"] == 3
    assert rows["RULES_ONLY"]["other_fraud"] == 0
    assert rows["HYBRID"].get("equals_detector") == "RULES_ONLY"
