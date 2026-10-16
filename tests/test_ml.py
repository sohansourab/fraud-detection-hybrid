"""Module P4a tests for the record-level ML scoring.

Covers the parts that must not silently drift:

* no feature name is a forbidden column (label / split / rule output);
* the two ported fixes (mobile missing indicator + imputation, explicit
  ``"other"`` procedure code);
* the threshold is chosen on the validation split only;
* the pipeline is deterministic (same seed -> identical ``ml_scores.csv``) and
  emits one row per scannable record.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.ml import (  # noqa: E402
    ALL_FEATURES,
    CIVIL_FEATURES,
    FORBIDDEN_FEATURES,
    MGNREGA_FEATURES,
    MLError,
    PMJAY_FEATURES,
    _encode_procedures,
    choose_threshold,
    civil_features,
    feature_names,
    mgnrega_features,
    pmjay_features,
    run,
)


def _civil_toy() -> pd.DataFrame:
    return pd.DataFrame({
        "BeneficiaryID": ["BEN_1", "BEN_2", "BEN_3", "BEN_4"],
        "Name": ["a", "b", "c", "d"],
        "Age": [30, 40, 50, 60],
        "Gender": ["M", "F", "O", "M"],
        "MobileNumber": ["1111111111", "2222222222", None, ""],
        "AadhaarHash": ["h1", "h2", "h3", "h4"],
        "FamilyID": ["F1", "F1", "F2", "F3"],
        "District": ["D1", "D1", "D2", "D2"],
        "JobCardID": ["JC1", None, "JC3", ""],
    })


def _mgnrega_toy() -> pd.DataFrame:
    return pd.DataFrame({
        "TransactionID": ["TXN_1", "TXN_2"],
        "JobCardID": ["JC1", "JC1"],
        "WorkCode": ["WC1", "WC2"],
        "MusterRollID": ["MR1", "MR1"],
        "WorkStartDate": ["2024-01-01", "2024-01-02"],
        "DaysWorked": [10, 20],
        "WageRate": [200, 200],
        "TotalAmount": [2000, 4000],
    })


def _pmjay_toy() -> pd.DataFrame:
    return pd.DataFrame({
        "ClaimID": ["CLM_1", "CLM_2"],
        "BeneficiaryID": ["BEN_1", "BEN_2"],
        "HospitalID": ["H1", "H1"],
        "AdmissionDate": ["2024-01-01", "2024-01-05"],
        "DischargeDate": ["2024-01-03", "2024-01-04"],
        "ProcedureName": ["A", "Z"],
        "ClaimAmount": [100, 200],
        "PatientStatus": ["Discharged", "Discharged"],
    })


def test_feature_names_have_no_forbidden_columns() -> None:
    for name in ALL_FEATURES:
        lowered = name.lower()
        for token in FORBIDDEN_FEATURES:
            assert token not in lowered, f"{name!r} contains forbidden {token!r}"


def test_builders_return_declared_columns() -> None:
    assert list(civil_features(_civil_toy()).columns) == list(CIVIL_FEATURES)
    assert list(mgnrega_features(_mgnrega_toy()).columns) == list(MGNREGA_FEATURES)
    assert list(pmjay_features(_pmjay_toy()).columns) == list(PMJAY_FEATURES)
    assert feature_names("civil_registry") == list(CIVIL_FEATURES)


def test_mobile_missing_indicator_and_imputation() -> None:
    """Fix 1: NaN and blank -> indicator + median imputation, never 0."""
    feats = civil_features(_civil_toy())

    assert feats["MobileNumber_missing"].tolist() == [0, 0, 1, 1]
    median = (1111111111 + 2222222222) / 2
    assert feats.loc[2, "MobileNumber_numeric"] == pytest.approx(median)
    assert feats.loc[3, "MobileNumber_numeric"] == pytest.approx(median)
    assert (feats["MobileNumber_numeric"] != 0).all()
    # Blank JobCardID is treated as missing too.
    assert feats["JobCard_exists"].tolist() == [1, 0, 1, 0]


def test_other_procedure_encoded_not_zero() -> None:
    """Fix 2: the leftover procedures get an explicit non-colliding code 0."""
    series = pd.Series(["A", "A", "B", "B", "C", "D", "E"])
    encoded = _encode_procedures(series, top_k=2)
    assert encoded.tolist() == [1, 1, 2, 2, 0, 0, 0]
    # "other" is exactly 0 and no top procedure maps to 0.
    assert set(encoded[series.isin(["C", "D", "E"])]) == {0}
    assert 0 not in set(encoded[series.isin(["A", "B"])])

    feats = pmjay_features(_pmjay_toy(), top_k=1)
    assert feats["Procedure_encoded"].tolist() == [1, 0]
    assert feats["LengthOfStay"].tolist() == [2, -1]


def test_other_procedure_code_when_count_exceeds_top_k() -> None:
    """With more procedures than top_k, the leftover really gets code 0."""
    series = pd.Series(["A"] * 4 + ["B"] * 3 + ["C"] * 2 + ["D"] * 1 + ["E"] * 1)
    encoded = _encode_procedures(series, top_k=3)
    assert set(encoded[series.isin(["D", "E"])]) == {0}       # explicit "other"
    assert set(encoded[series.isin(["A", "B", "C"])]) == {1, 2, 3}
    assert 0 not in set(encoded[series.isin(["A", "B", "C"])])


def test_threshold_chosen_on_val_only() -> None:
    val = pd.DataFrame({
        "ml_score": [0.5, 0.4, 0.3, 0.2],
        "is_fraud": [1, 1, 0, 0],
        "split": ["val", "val", "val", "val"],
    })
    assert isinstance(choose_threshold(val, 0.5), float)

    test = pd.DataFrame({
        "ml_score": [0.5],
        "is_fraud": [1],
        "split": ["test"],
    })
    with pytest.raises(MLError):
        choose_threshold(test, 0.5)


def test_pipeline_deterministic_and_complete(tmp_path: Path) -> None:
    labels_path = REPO_ROOT / "data" / "labels.csv"
    if not labels_path.is_file():
        pytest.skip("data/labels.csv not generated in this checkout")

    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    df = run(out_path=first)
    run(out_path=second)

    assert (
        hashlib.md5(first.read_bytes()).hexdigest()
        == hashlib.md5(second.read_bytes()).hexdigest()
    )
    labels = pd.read_csv(labels_path, keep_default_na=False)
    assert len(df) == len(labels)
    assert list(df.columns) == ["record_id", "domain", "ml_score", "ml_flag", "split"]
    assert df["record_id"].is_unique
    assert set(df["split"]) <= {"train", "val", "test"}
    assert set(df["ml_flag"]) <= {0, 1}
