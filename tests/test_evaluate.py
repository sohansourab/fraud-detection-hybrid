"""Module P3 tests for the evaluation harness.

Covers the parts that must not silently drift:

* a missing ``labels.csv`` fails loudly with the regeneration command;
* a trivially perfect detector scores precision = recall = F1 = 1.0;
* a flag on an ``is_fraud=0`` record counts as an FP;
* a rule with fewer than ``min_events`` injected events is "not evaluable";
* the ML_ONLY / HYBRID detector rows are present and null, not zero;
* every emitted flag reconciles: ``flagged == TP + FP``.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import audit_scanner  # noqa: E402
from fraud.config import get_config  # noqa: E402
from fraud.evaluate import (  # noqa: E402
    EvaluationError,
    assert_reconciliation,
    build_payload,
    load_labels,
    reconciliation_violations,
    rule_scores,
)


def _toy(record_ids, is_fraud, injected):
    return pd.DataFrame({
        "record_id": record_ids,
        "is_fraud": is_fraud,
        "injected_rule_id": injected,
    })


def test_missing_labels_raises(tmp_path: Path) -> None:
    repo_data = REPO_ROOT / "data"
    if not (repo_data / "labels.csv").is_file():
        pytest.skip("data/labels.csv not generated in this checkout")

    copy = tmp_path / "data"
    shutil.copytree(repo_data, copy)
    (copy / "labels.csv").unlink()  # delete it in the temp copy

    with pytest.raises(FileNotFoundError) as excinfo:
        load_labels(copy / "labels.csv")
    assert "data_simulator.py" in str(excinfo.value)


def test_perfect_detector_scores_one() -> None:
    labels = _toy(["BEN_1", "BEN_2"], [1, 1], ["RULE_001", "RULE_001"])
    flags = {"RULE_001": {"BEN_1", "BEN_2"}}

    scores = {s.rule_id: s for s in rule_scores(labels, flags, min_events=1)}
    score = scores["RULE_001"]
    assert (score.precision, score.recall, score.f1) == (1.0, 1.0, 1.0)
    assert score.evaluation_status == "in-sample"
    assert (score.tp, score.fp, score.fn) == (2, 0, 0)


def test_flag_on_clean_record_is_fp() -> None:
    labels = _toy(["BEN_1", "BEN_2"], [1, 0], ["RULE_001", ""])
    flags = {"RULE_001": {"BEN_1", "BEN_2"}}  # BEN_2 is is_fraud=0

    score = {s.rule_id: s for s in rule_scores(labels, flags, min_events=1)}["RULE_001"]
    assert (score.tp, score.fp, score.fn) == (1, 1, 0)
    assert score.precision == pytest.approx(0.5)
    assert score.recall == pytest.approx(1.0)


def test_few_events_is_not_evaluable() -> None:
    labels = _toy(["BEN_1"], [1], ["RULE_001"])
    flags = {"RULE_001": {"BEN_1"}}

    score = {s.rule_id: s for s in rule_scores(labels, flags, min_events=10)}["RULE_001"]
    assert score.evaluation_status == "not evaluable"
    assert score.precision is None and score.recall is None and score.f1 is None


def test_detector_rows_include_unbuilt_ml_and_hybrid() -> None:
    payload = build_payload({"0.02": []}, get_config())
    detectors = {d["detector"]: d for d in payload["detectors"]}
    for name in ("ML_ONLY", "HYBRID"):
        assert detectors[name]["evaluation_status"] == "not built (P4)"
        assert detectors[name]["precision"] is None
        assert detectors[name]["recall"] is None
        assert detectors[name]["f1"] is None


def test_reconciliation_guard_flags_cross_rule_flag() -> None:
    """A flag on a fraud record injected with a *different* rule is unaccounted.

    RULE_001 flags both BEN_1 (injected RULE_001) and BEN_2 (injected RULE_002).
    BEN_2 is fraud but is not a positive for RULE_001, so the current FP
    definition (flags on ``is_fraud=0`` only) leaves it out and
    ``flagged != TP + FP``. This is the reconciliation bug P3b must fix.
    """
    labels = _toy(["BEN_1", "BEN_2"], [1, 1], ["RULE_001", "RULE_002"])
    flags = {"RULE_001": {"BEN_1", "BEN_2"}}

    score = {s.rule_id: s for s in rule_scores(labels, flags, min_events=1)}["RULE_001"]
    assert (score.flagged, score.tp, score.fp) == (2, 1, 0)

    assert reconciliation_violations([score]) == [
        "RULE_001: flagged=2 != TP+FP=1 (unaccounted flags=1)"
    ]
    with pytest.raises(EvaluationError):
        assert_reconciliation([score])


def test_reconciliation_guard_accepts_consistent_rows() -> None:
    """A rule whose flags are all TP or ``is_fraud=0`` FP reconciles."""
    labels = _toy(["BEN_1", "BEN_2"], [1, 0], ["RULE_001", ""])
    flags = {"RULE_001": {"BEN_1", "BEN_2"}}

    score = {s.rule_id: s for s in rule_scores(labels, flags, min_events=1)}["RULE_001"]
    assert (score.flagged, score.tp, score.fp) == (2, 1, 1)

    assert reconciliation_violations([score]) == []
    assert_reconciliation([score])  # must not raise


def test_payload_records_floor_and_reconciliation() -> None:
    cfg = get_config()
    payload = build_payload({"0.02": []}, cfg)
    assert payload["mega_family_floor"] == cfg.civil_registry.max_family_size + 1
    assert payload["reconciliation_ok"] is True
    assert payload["reconciliation_violations"] == []


@pytest.mark.xfail(
    strict=True,
    reason="FP undercounts flags on fraud records injected with another rule; "
    "fix in P3b. Remove this marker once the rows reconcile.",
)
def test_repo_flags_reconcile() -> None:
    """Every rule row from the real synthetic data must satisfy flagged == TP+FP."""
    labels_path = REPO_ROOT / "data" / "labels.csv"
    if not labels_path.is_file():
        pytest.skip("data/labels.csv not generated in this checkout")

    scanner = audit_scanner.MasterFraudScanner()
    scanner.run_all_scans()
    flags: dict[str, set[str]] = {}
    for report in scanner.all_reports:
        for flag in report.flags:
            flags.setdefault(flag["rule_id"], set()).add(report.record_id)

    labels = load_labels(labels_path)
    scores = rule_scores(labels, flags, get_config().simulator.min_events_per_type)
    assert_reconciliation(scores)
