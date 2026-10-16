"""Loader for the real Kaggle IEEE-CIS Fraud Detection dataset (module R1).

This module only reads the CSVs under ``data/external/ieee-cis`` and writes a
single modelling table. The synthetic pipeline is untouched. Behaviour:

* LEFT join of transactions to identity on ``TransactionID`` - every
  transaction row survives and ``identity_present`` records whether an identity
  row matched.
* An explicit, configured null policy (``configs/external.yaml``): any column
  whose null fraction exceeds the threshold is dropped and reported; every kept
  column with nulls gets a ``<col>_missing`` flag plus an imputed value (median
  for numeric, a sentinel string for text). Medians are computed on TRAIN rows
  only, so val/test cannot leak into the imputation.
* A quantile time split on ``TransactionDT`` into train / val / test.

``isFraud`` is read only to emit the label column ``is_fraud``; it never feeds
a feature or an imputation statistic.
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXTERNAL_CONFIG_PATH = REPO_ROOT / "configs" / "external.yaml"

ID_COLUMN = "TransactionID"
LABEL_COLUMN = "isFraud"
TIME_COLUMN = "TransactionDT"
MISSING_SENTINEL = "__missing__"

#: Output columns that are never treated as features and never imputed.
RESERVED_COLUMNS = [
    "transaction_id",
    "split",
    "is_fraud",
    "identity_present",
    "TransactionDT",
]
SPLIT_ORDER = ("train", "val", "test")


@dataclass(frozen=True)
class IeeeCisConfig:
    """Settings for the IEEE-CIS loader (mirrors ``configs/external.yaml``)."""

    data_dir: str = "data/external/ieee-cis"
    transaction_file: str = "train_transaction.csv"
    identity_file: str = "train_identity.csv"
    processed_file: str = "processed.parquet"
    null_drop_threshold: float = 0.90
    missing_sentinel: str = MISSING_SENTINEL
    val_start_quantile: float = 0.60
    test_start_quantile: float = 0.80


@dataclass
class LoadReport:
    """What the loader did, so callers can print or assert on it."""

    dropped_columns: list[str] = field(default_factory=list)
    boundaries: dict[str, float] = field(default_factory=dict)
    rows_per_split: dict[str, int] = field(default_factory=dict)
    fraud_rate_per_split: dict[str, float] = field(default_factory=dict)
    feature_columns: list[str] = field(default_factory=list)
    output_path: Path | None = None
    md5: str = ""


def load_external_config(path: str | Path | None = None) -> IeeeCisConfig:
    """Load ``configs/external.yaml``, falling back to dataclass defaults."""
    config_path = Path(path) if path is not None else DEFAULT_EXTERNAL_CONFIG_PATH
    if not config_path.is_file():
        logger.warning("Config %s not found; using built-in defaults", config_path)
        return IeeeCisConfig()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    section = raw.get("ieee_cis", raw)
    known = {f.name for f in fields(IeeeCisConfig)}
    return IeeeCisConfig(**{k: v for k, v in section.items() if k in known})


def resolve_input_file(data_dir: str | Path, name: str) -> Path:
    """Return the CSV path for ``name`` inside ``data_dir``.

    Some unzip tools create an extra directory level whose name equals the
    file, so ``<data_dir>/<name>/<name>`` is accepted as a fallback for the
    expected ``<data_dir>/<name>``.
    """
    candidate = Path(data_dir) / name
    if candidate.is_file():
        return candidate
    nested = candidate / name
    if nested.is_file():
        logger.warning("Using nested data file %s", nested)
        return nested
    raise FileNotFoundError(
        f"Expected {candidate} (or nested {nested}) - is the IEEE-CIS data present?"
    )


def _parquet_available() -> bool:
    return importlib.util.find_spec("pyarrow") is not None


def frame_md5(frame: pd.DataFrame) -> str:
    """Deterministic MD5 over a canonical CSV rendering of ``frame``."""
    return hashlib.md5(frame.to_csv(index=False).encode("utf-8")).hexdigest()


def assign_time_split(
    frame: pd.DataFrame,
    val_start_quantile: float,
    test_start_quantile: float,
) -> dict[str, float]:
    """Add a ``split`` column using quantile cut points on ``TransactionDT``.

    Boundaries are ``<=`` so every row lands in exactly one split and
    max(train) < min(val) <= max(val) < min(test) even when timestamps tie.
    """
    if not 0.0 < val_start_quantile < test_start_quantile < 1.0:
        raise ValueError(
            "quantiles must satisfy 0 < val_start < test_start < 1, got "
            f"{val_start_quantile}, {test_start_quantile}"
        )
    dt = frame[TIME_COLUMN].to_numpy()
    boundary_val = float(np.quantile(dt, val_start_quantile))
    boundary_test = float(np.quantile(dt, test_start_quantile))
    if not boundary_val < boundary_test:
        raise ValueError(
            f"TransactionDT quantiles collapsed: val={boundary_val} test={boundary_test}"
        )
    frame["split"] = np.where(
        dt <= boundary_val,
        "train",
        np.where(dt <= boundary_test, "val", "test"),
    )
    return {"val_start": boundary_val, "test_start": boundary_test}


def apply_null_policy(
    frame: pd.DataFrame,
    feature_columns: list[str],
    threshold: float,
    sentinel: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Drop sparse columns, then flag and impute the remaining nulls.

    Returns ``(frame, dropped_columns, kept_feature_columns)``. Numeric medians
    come from train rows only.
    """
    dropped = [c for c in feature_columns if frame[c].isna().mean() > threshold]
    if dropped:
        frame = frame.drop(columns=dropped)
    kept = [c for c in feature_columns if c not in dropped]

    train_mask = (frame["split"] == "train").to_numpy()
    # Build every imputed column and missing flag in one pass (avoids the
    # highly-fragmented-frame warnings from inserting hundreds of columns).
    rebuilt: dict[str, pd.Series] = {}
    for col in kept:
        nulls = frame[col].isna()
        if not nulls.any():
            continue
        if pd.api.types.is_numeric_dtype(frame[col]):
            median = frame.loc[train_mask, col].median()
            if pd.isna(median):
                logger.warning(
                    "Column %s has nulls but no train values; imputing 0.0", col
                )
                median = 0.0
            rebuilt[col] = frame[col].fillna(median)
        else:
            rebuilt[col] = frame[col].fillna(sentinel)
        # Flag is added after its column so it does not erase the signal.
        rebuilt[f"{col}_missing"] = nulls.astype(int)

    if rebuilt:
        replaced = [c for c in rebuilt if c in frame.columns]
        untouched = frame.drop(columns=replaced)
        frame = pd.concat(
            [untouched, pd.DataFrame(rebuilt, index=frame.index)], axis=1
        )
        frame = frame[list(untouched.columns) + list(rebuilt)]
    return frame, dropped, kept


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = set(RESERVED_COLUMNS) | {ID_COLUMN, LABEL_COLUMN}
    return [c for c in frame.columns if c not in excluded]


def _order_columns(feature_columns: list[str], present: set[str]) -> list[str]:
    """Reserved schema first, then each feature followed by its missing flag."""
    ordered = [c for c in RESERVED_COLUMNS if c in present]
    for col in feature_columns:
        ordered.append(col)
        indicator = f"{col}_missing"
        if indicator in present:
            ordered.append(indicator)
    return ordered


def _write_processed(frame: pd.DataFrame, base_dir: Path, cfg: IeeeCisConfig) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    if _parquet_available():
        path = base_dir / cfg.processed_file
        frame.to_parquet(path, index=False)
        return path
    path = (base_dir / cfg.processed_file).with_suffix(".csv")
    frame.to_csv(path, index=False)
    logger.warning("pyarrow not installed; wrote CSV instead of parquet: %s", path)
    return path


def build_ieee_cis(
    data_dir: str | Path | None = None,
    config: IeeeCisConfig | None = None,
    *,
    write: bool = True,
) -> tuple[pd.DataFrame, LoadReport]:
    """Load, join, split, clean and (by default) write the IEEE-CIS table."""
    cfg = config or load_external_config()
    base_dir = Path(data_dir) if data_dir is not None else REPO_ROOT / cfg.data_dir

    transaction_path = resolve_input_file(base_dir, cfg.transaction_file)
    identity_path = resolve_input_file(base_dir, cfg.identity_file)
    logger.info("Reading transactions: %s", transaction_path)
    transactions = pd.read_csv(transaction_path, low_memory=False)
    logger.info("Read %d transaction rows x %d columns", *transactions.shape)
    logger.info("Reading identity: %s", identity_path)
    identity = pd.read_csv(identity_path, low_memory=False)

    # Mark matches before the join: every identity row contributes a 1.
    identity["identity_present"] = 1
    frame = transactions.merge(
        identity, on=ID_COLUMN, how="left", validate="many_to_one"
    )
    if len(frame) != len(transactions):
        raise ValueError(
            f"left join lost rows: {len(transactions)} -> {len(frame)}"
        )
    # Defragment after the wide merge so the column inserts below are cheap.
    frame = frame.copy()
    frame["identity_present"] = frame["identity_present"].fillna(0).astype(int)

    frame["transaction_id"] = frame[ID_COLUMN].astype(int)
    frame["is_fraud"] = frame[LABEL_COLUMN].astype(int)
    boundaries = assign_time_split(
        frame, cfg.val_start_quantile, cfg.test_start_quantile
    )

    frame, dropped, kept = apply_null_policy(
        frame, _feature_columns(frame), cfg.null_drop_threshold, cfg.missing_sentinel
    )
    leaked = set(kept) & ({LABEL_COLUMN, "is_fraud"} | {ID_COLUMN})
    if leaked:
        raise ValueError(f"label/id leaked into features: {sorted(leaked)}")
    frame = frame[_order_columns(kept, set(frame.columns))]

    report = LoadReport(
        dropped_columns=dropped,
        boundaries=boundaries,
        rows_per_split={
            s: int((frame["split"] == s).sum()) for s in SPLIT_ORDER
        },
        fraud_rate_per_split={
            s: float(frame.loc[frame["split"] == s, "is_fraud"].mean())
            for s in SPLIT_ORDER
        },
        feature_columns=kept,
        md5=frame_md5(frame),
    )
    if write:
        report.output_path = _write_processed(frame, base_dir, cfg)
        logger.info("Wrote %s (md5=%s)", report.output_path, report.md5)
    return frame, report


def load_ieee_cis(
    data_dir: str | Path | None = None,
    config: IeeeCisConfig | None = None,
) -> pd.DataFrame:
    """Return the processed IEEE-CIS table (see :func:`build_ieee_cis`)."""
    frame, report = build_ieee_cis(data_dir, config)
    logger.info("%s", format_report(report))
    return frame


def format_report(report: LoadReport) -> str:
    """Human-readable one-shot summary of what the loader did."""
    total = sum(report.rows_per_split.values())
    lines = [f"IEEE-CIS rows: {total} (synthetic-free real data)"]
    for split in SPLIT_ORDER:
        lines.append(
            f"  {split:>5}: rows={report.rows_per_split.get(split, 0):>7} "
            f"fraud_rate={report.fraud_rate_per_split.get(split, float('nan')):.4f}"
        )
    lines.append(
        "TransactionDT boundaries: "
        f"val_start={report.boundaries.get('val_start', float('nan')):.1f} "
        f"test_start={report.boundaries.get('test_start', float('nan')):.1f}"
    )
    lines.append(
        f"Dropped columns (>0.90 null): {len(report.dropped_columns)} "
        f"{report.dropped_columns}"
    )
    lines.append(f"Features: {len(report.feature_columns)}  MD5: {report.md5}")
    if report.output_path is not None:
        lines.append(f"Output: {report.output_path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``python -m fraud.external.ieee_cis``."""
    import argparse

    parser = argparse.ArgumentParser(description="Load the real IEEE-CIS dataset.")
    parser.add_argument("--data-dir", default=None, help="folder with the CSVs")
    parser.add_argument("--no-write", action="store_true", help="skip the output file")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    frame, report = build_ieee_cis(args.data_dir, write=not args.no_write)
    print(format_report(report))
    return 0 if not frame.empty else 1


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    raise SystemExit(main())
