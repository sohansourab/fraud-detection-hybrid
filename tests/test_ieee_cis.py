"""Module R1 tests for the real-data IEEE-CIS loader.

These run against a tiny synthetic fixture written to ``tmp_path`` (never the
real 683 MB CSVs). They guard the three things R1 can silently get wrong:

* the LEFT join keeps every transaction row and flags matched identity rows;
* the null policy drops sparse columns and imputes numeric values with the
  TRAIN median only (a val outlier must not move it), and never leaks the
  label into a feature;
* the quantile time split is disjoint and monotone, and the loader is
  deterministic (same input -> identical bytes).

One optional test runs the loader on the real files when they are present.
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

from fraud.external.ieee_cis import (  # noqa: E402
    IeeeCisConfig,
    build_ieee_cis,
    frame_md5,
    resolve_input_file,
)

MATCHED_IDS = {2, 4, 6}
REAL_DATA_DIR = REPO_ROOT / "data" / "external" / "ieee-cis"


def _write_fixture(base: Path) -> Path:
    """Ten transactions with a matched/unmatched identity and a val outlier."""
    base.mkdir(parents=True, exist_ok=True)
    transactions = pd.DataFrame(
        {
            "TransactionID": list(range(1, 11)),
            "isFraud": [0, 1, 0, 0, 0, 1, 0, 0, 1, 0],
            "TransactionDT": list(range(1, 11)),
            # Row 6 (train) is null; row 7 (val) is a wild outlier.
            "numeric_feature": [10, 20, 30, 40, 50, None, 1e9, 60, 70, 80],
            "text_feature": ["a", "b", None, "d", "e", "f", "g", None, "i", "j"],
            # 10/10 null -> null fraction 1.0 > 0.90 -> must be dropped.
            "mostly_null": [None] * 10,
        }
    )
    transactions.to_csv(base / "train_transaction.csv", index=False)

    identity = pd.DataFrame(
        {
            "TransactionID": sorted(MATCHED_IDS),
            "id_01": [1.0, 2.0, 3.0],
            "DeviceType": ["mobile", "desktop", "mobile"],
        }
    )
    identity.to_csv(base / "train_identity.csv", index=False)
    return base


def _build(tmp_path: Path, write: bool = True):
    return build_ieee_cis(tmp_path, config=IeeeCisConfig(), write=write)


def test_left_join_keeps_every_transaction_row(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    frame, _ = _build(tmp_path)
    assert len(frame) == 10
    assert set(frame["transaction_id"]) == set(range(1, 11))


def test_identity_present_flags_matched_and_unmatched(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    frame, _ = _build(tmp_path)
    flags = frame.set_index("transaction_id")["identity_present"]
    for transaction_id, expected in flags.items():
        assert expected == int(transaction_id in MATCHED_IDS), transaction_id


def test_sparse_column_is_dropped_and_reported(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    frame, report = _build(tmp_path)
    assert report.dropped_columns == ["mostly_null"]
    assert "mostly_null" not in frame.columns
    assert "mostly_null_missing" not in frame.columns


def test_median_imputation_uses_train_rows_only(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    frame, _ = _build(tmp_path)
    row = frame.set_index("transaction_id")

    # Train non-null values are [10, 20, 30, 40, 50] -> median 30. A single-val
    # statistic would be dragged to 50 by the 1e9 outlier on transaction 7.
    assert row.loc[6, "numeric_feature"] == 30.0
    # The outlier itself must be left untouched, not clipped to the median.
    assert row.loc[7, "numeric_feature"] == 1e9
    # The missing flag marks where the imputation happened.
    assert row.loc[6, "numeric_feature_missing"] == 1
    assert row.loc[1, "numeric_feature_missing"] == 0
    # Text nulls get the sentinel, not a median.
    assert row.loc[3, "text_feature"] == "__missing__"
    assert row.loc[8, "text_feature"] == "__missing__"


def test_splits_are_disjoint_and_monotone(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    frame, report = _build(tmp_path)

    assert set(frame["split"]) == {"train", "val", "test"}
    # Every row belongs to exactly one split by construction; verify counts.
    assert report.rows_per_split == {"train": 6, "val": 2, "test": 2}

    train = frame.loc[frame["split"] == "train", "TransactionDT"]
    val = frame.loc[frame["split"] == "val", "TransactionDT"]
    test = frame.loc[frame["split"] == "test", "TransactionDT"]
    assert train.max() <= val.min() - 1
    assert val.max() <= test.min() - 1
    assert report.boundaries["val_start"] < report.boundaries["test_start"]


def test_label_never_becomes_a_feature(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    frame, report = _build(tmp_path)
    forbidden = {"isFraud", "is_fraud", "TransactionID", "transaction_id"}
    assert not (set(report.feature_columns) & forbidden)
    assert "is_fraud" in frame.columns  # label present, but reserved


def test_same_input_gives_identical_output_bytes(tmp_path: Path) -> None:
    first_dir = _write_fixture(tmp_path / "first")
    second_dir = _write_fixture(tmp_path / "second")
    first, _ = _build(first_dir)
    second, _ = _build(second_dir)

    assert frame_md5(first) == frame_md5(second)
    first_bytes = (first_dir / "processed.parquet").read_bytes()
    second_bytes = (second_dir / "processed.parquet").read_bytes()
    assert first_bytes == second_bytes


def _real_files_present() -> bool:
    try:
        resolve_input_file(REAL_DATA_DIR, "train_transaction.csv")
        resolve_input_file(REAL_DATA_DIR, "train_identity.csv")
    except FileNotFoundError:
        return False
    return True


@pytest.mark.skipif(not _real_files_present(), reason="real IEEE-CIS CSVs absent")
def test_real_dataset_keeps_every_transaction() -> None:
    frame, report = build_ieee_cis(REAL_DATA_DIR, write=False)
    assert len(frame) == 590_540
    assert sum(report.rows_per_split.values()) == 590_540
    assert frame["identity_present"].isin([0, 1]).all()
