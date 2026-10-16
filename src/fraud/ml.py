"""Record-level ML anomaly scoring (module P4a).

A hybrid companion to the rule engine: three per-domain IsolationForest models
produce a continuous anomaly score per scannable record. Features come from the
raw domain columns only; no label, split or rule-output column is ever a
feature.

Two issues in the original ``ml_anomaly_detector.py`` are fixed while porting:

* **Civil ``MobileNumber`` -> numeric.** NaN and blank values previously became
  ``0``. They now produce an explicit ``MobileNumber_missing`` indicator *and* a
  real imputed value (the median of the valid numbers), so "missing" is not
  confused with a genuine zero.
* **PM-JAY ``Procedure_encoded``.** The old code mapped both the first top
  procedure and every unknown procedure to ``0``. Top procedures now get codes
  ``1..K`` and the leftover is an explicit ``"other"`` code ``0``, so the two
  can never collide.

Scoring: ``contamination="auto"`` (no fixed 5% cutoff), ``n_estimators`` and
``random_state`` from config. The model is fit on the **train** split with a
stratified validation subset held out; the score threshold (precision >=
``ml.precision_target``) is chosen on that validation subset only. The raw
continuous score is ``-IsolationForest.score_samples`` (higher = more
anomalous). Output is one row per scannable record in ``reports/ml_scores.csv``.

Run with::

    python -m fraud.ml
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from fraud.config import Config, get_config

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_SCORES_CSV = REPO_ROOT / "reports" / "ml_scores.csv"

#: Labels ``domain`` value -> internal domain key.
DOMAIN_BY_LABEL: dict[str, str] = {
    "Civil Registry": "civil_registry",
    "MGNREGA Labor": "mgnrega",
    "PM-JAY Medical": "pmjay",
}
LABEL_BY_DOMAIN: dict[str, str] = {v: k for k, v in DOMAIN_BY_LABEL.items()}

#: Raw join key for each domain (the labels ``record_id`` column).
ID_COLUMN: dict[str, str] = {
    "civil_registry": "BeneficiaryID",
    "mgnrega": "TransactionID",
    "pmjay": "ClaimID",
}

#: Tokens that must never appear in a feature name.
FORBIDDEN_FEATURES: tuple[str, ...] = (
    "is_fraud",
    "fraud_type",
    "injected_rule_id",
    "split",
    "flag",
    "rule",
)

CIVIL_FEATURES: tuple[str, ...] = (
    "Age",
    "MobileNumber_numeric",
    "MobileNumber_missing",
    "JobCard_exists",
    "Gender_encoded",
    "FamilySize",
)
MGNREGA_FEATURES: tuple[str, ...] = (
    "DaysWorked",
    "WageRate",
    "TotalAmount",
    "Amount_per_day",
    "JobCard_frequency",
)
PMJAY_FEATURES: tuple[str, ...] = (
    "ClaimAmount",
    "LengthOfStay",
    "Hospital_claim_frequency",
    "Procedure_encoded",
)

FEATURES_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    "civil_registry": CIVIL_FEATURES,
    "mgnrega": MGNREGA_FEATURES,
    "pmjay": PMJAY_FEATURES,
}
ALL_FEATURES: tuple[str, ...] = CIVIL_FEATURES + MGNREGA_FEATURES + PMJAY_FEATURES


def feature_names(domain: str) -> list[str]:
    """Ordered feature names used for ``domain``."""
    return list(FEATURES_BY_DOMAIN[domain])


def _blank_to_na(series: pd.Series) -> pd.Series:
    """Treat empty/whitespace strings as missing (in addition to real NaN)."""
    return series.where(series.astype(str).str.strip() != "")


def _encode_procedures(series: pd.Series, top_k: int) -> pd.Series:
    """Map the ``top_k`` most common procedures to 1..K and the rest to 0.

    ``0`` is an explicit ``"other"`` code, so it never collides with a top
    procedure (fix 2).
    """
    counts = series.astype(str).value_counts()
    top = list(counts.head(top_k).index)
    codes = {name: index + 1 for index, name in enumerate(top)}
    return series.astype(str).map(codes).fillna(0).astype(int)


def civil_features(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric features for the Civil Registry rows."""
    out = pd.DataFrame(index=df.index)
    out["Age"] = pd.to_numeric(df["Age"], errors="coerce").fillna(0)

    mobile = pd.to_numeric(_blank_to_na(df["MobileNumber"]), errors="coerce")
    out["MobileNumber_missing"] = mobile.isna().astype(int)
    median = mobile.median()
    out["MobileNumber_numeric"] = mobile.fillna(median if pd.notna(median) else 0.0)

    out["JobCard_exists"] = (
        _blank_to_na(df["JobCardID"]).notna().astype(int)
    )
    out["Gender_encoded"] = (
        df["Gender"].map({"M": 0, "F": 1, "O": 2}).fillna(0).astype(int)
    )
    family_counts = df["FamilyID"].value_counts()
    out["FamilySize"] = df["FamilyID"].map(family_counts).fillna(1)
    return out[list(CIVIL_FEATURES)]


def mgnrega_features(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric features for the MGNREGA transaction rows."""
    out = pd.DataFrame(index=df.index)
    days = pd.to_numeric(df["DaysWorked"], errors="coerce").fillna(0)
    wage = pd.to_numeric(df["WageRate"], errors="coerce").fillna(0)
    total = pd.to_numeric(df["TotalAmount"], errors="coerce").fillna(0)
    out["DaysWorked"] = days
    out["WageRate"] = wage
    out["TotalAmount"] = total
    out["Amount_per_day"] = np.where(days > 0, total / days, 0)
    card_counts = df["JobCardID"].value_counts()
    out["JobCard_frequency"] = df["JobCardID"].map(card_counts).fillna(0)
    return out[list(MGNREGA_FEATURES)]


def pmjay_features(df: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    """Numeric features for the PM-JAY claim rows."""
    out = pd.DataFrame(index=df.index)
    admission = pd.to_datetime(df["AdmissionDate"], errors="coerce")
    discharge = pd.to_datetime(df["DischargeDate"], errors="coerce")
    out["ClaimAmount"] = pd.to_numeric(df["ClaimAmount"], errors="coerce").fillna(0)
    out["LengthOfStay"] = (discharge - admission).dt.days.fillna(0)
    hospital_counts = df["HospitalID"].value_counts()
    out["Hospital_claim_frequency"] = df["HospitalID"].map(hospital_counts).fillna(0)
    out["Procedure_encoded"] = _encode_procedures(df["ProcedureName"], top_k)
    return out[list(PMJAY_FEATURES)]


# =============================================================================
# THRESHOLD SELECTION
# =============================================================================

class MLError(RuntimeError):
    """Raised when ML scoring is asked to do something invalid."""


def choose_threshold(val: pd.DataFrame, target: float) -> float:
    """Lowest score threshold whose validation precision is >= ``target``.

    ``val`` must be the validation split only; passing any other split is an
    error (the test split must never influence the threshold).
    """
    if "split" in val.columns and set(val["split"].astype(str)) - {"val"}:
        raise MLError(
            "threshold must be chosen on the validation split only, got splits: "
            f"{sorted(set(val['split'].astype(str)))}"
        )
    if val.empty:
        return float("inf")

    scores = val["ml_score"].to_numpy(dtype=float)
    y = val["is_fraud"].to_numpy(dtype=int)
    positives = int(y.sum())

    best_eligible: tuple[tuple[float, float, float], float] | None = None
    best_precision: tuple[float, float] | None = None
    for threshold in np.unique(scores):  # ascending
        flagged = scores >= threshold
        tp = int((flagged & (y == 1)).sum())
        fp = int((flagged & (y == 0)).sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / positives if positives else 0.0
        if precision >= target:
            # Maximise recall, then precision, then prefer the lower threshold.
            key = (recall, precision, -float(threshold))
            if best_eligible is None or key > best_eligible[0]:
                best_eligible = (key, float(threshold))
        if best_precision is None or precision > best_precision[0]:
            best_precision = (precision, float(threshold))

    if best_eligible is not None:
        return best_eligible[1]
    # No threshold reaches the target: fall back to the highest-precision one.
    logger.warning(
        "no validation threshold reached precision >= %.2f; using best precision %.2f",
        target, best_precision[0] if best_precision else 0.0,
    )
    return best_precision[1] if best_precision else float("inf")


# =============================================================================
# SCORING
# =============================================================================

def _carve_val(
    train_pos: np.ndarray, y: np.ndarray, fraction: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Split ``train_pos`` into (fit, val); stratify on ``y`` when possible."""
    train_pos = np.asarray(train_pos, dtype=int)
    if fraction <= 0 or len(train_pos) < 2:
        return train_pos, np.array([], dtype=int)
    y_train = y[train_pos]
    values, counts = np.unique(y_train, return_counts=True)
    stratify = y_train if len(values) == 2 and counts.min() >= 2 else None
    fit_pos, val_pos = train_test_split(
        train_pos, test_size=fraction, random_state=seed, stratify=stratify
    )
    return np.asarray(fit_pos, dtype=int), np.asarray(val_pos, dtype=int)


def score_domain(
    domain: str, df: pd.DataFrame, labels: pd.DataFrame, cfg: Config
) -> pd.DataFrame:
    """Fit one IsolationForest for ``domain`` and score every scannable row.

    ``labels`` is the labels subset for this domain (``record_id``, ``is_fraud``,
    ``split``). The model is fit on the train split minus a held-out validation
    subset; the validation subset only sets the threshold.
    """
    features = {
        "civil_registry": civil_features,
        "mgnrega": mgnrega_features,
        "pmjay": lambda frame: pmjay_features(frame, cfg.ml.top_procedures),
    }[domain](df)
    features.index = df[ID_COLUMN[domain]].astype(str)

    subset = labels.set_index("record_id")
    features = features.loc[subset.index]
    y = subset["is_fraud"].astype(int).to_numpy()
    splits = subset["split"].astype(str).to_numpy().astype(object)

    train_pos = np.flatnonzero(splits == "train")
    fit_pos, val_pos = _carve_val(train_pos, y, cfg.ml.val_fraction, cfg.seed)
    effective = splits.copy()
    effective[val_pos] = "val"

    scaler = StandardScaler()
    x_fit = scaler.fit_transform(features.iloc[fit_pos])
    model = IsolationForest(
        n_estimators=cfg.ml.n_estimators,
        contamination=cfg.ml.contamination,
        random_state=cfg.ml.random_state,
    )
    model.fit(x_fit)
    scores = -model.score_samples(scaler.transform(features))

    out = pd.DataFrame({
        "record_id": features.index.to_numpy(),
        "domain": domain,
        "ml_score": scores,
        "split": effective,
        "is_fraud": y,
    })
    threshold = choose_threshold(out[out["split"] == "val"], cfg.ml.precision_target)
    out["ml_flag"] = (out["ml_score"] >= threshold).astype(int)
    out["threshold"] = threshold
    return out


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else REPO_ROOT / path


def run(write: bool = True, out_path: str | Path | None = None) -> pd.DataFrame:
    """Score every scannable record and (optionally) write ``ml_scores.csv``."""
    cfg = get_config()
    labels = pd.read_csv(_resolve(cfg.paths.labels), keep_default_na=False)
    paths: dict[str, str] = {
        "civil_registry": cfg.paths.beneficiaries,
        "mgnrega": cfg.paths.mgnrega,
        "pmjay": cfg.paths.pmjay,
    }

    parts: list[pd.DataFrame] = []
    for label_name, domain in DOMAIN_BY_LABEL.items():
        subset = labels[labels["domain"] == label_name]
        if subset.empty:
            continue
        df = pd.read_csv(_resolve(paths[domain]), keep_default_na=False)
        result = score_domain(domain, df, subset, cfg)
        result["domain"] = label_name
        logger.info(
            "[ml] %s: scored=%d flagged=%d threshold=%.4f",
            label_name,
            len(result),
            int(result["ml_flag"].sum()),
            float(result["threshold"].iloc[0]),
        )
        parts.append(result)

    out = pd.concat(parts, ignore_index=True)
    out = out.set_index("record_id").loc[labels["record_id"].astype(str)].reset_index()
    out = out[["record_id", "domain", "ml_score", "ml_flag", "split"]]

    if write:
        path = Path(out_path) if out_path is not None else ML_SCORES_CSV
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path, index=False)
        logger.info("[ml] wrote %d rows to %s", len(out), path)
    return out


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Record-level ML anomaly scoring.")
    parser.add_argument(
        "--out", default=None,
        help="Output CSV path (default: reports/ml_scores.csv).",
    )
    args = parser.parse_args(argv)
    run(out_path=args.out)


if __name__ == "__main__":
    main()
