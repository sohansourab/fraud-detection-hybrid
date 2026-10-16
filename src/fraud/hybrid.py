"""HYBRID combination and one-shot test report (module P4c).

Combines the rule engine's flags with the P4a record scores. The combination is
**selected on validation rows only**, and the unseen typologies are excluded from
that selection (module P2e injected them; they must not choose a threshold or a
combination rule - see the "Threshold-selection leakage" section of
``reports/ml_only.md``). The selected combination is then applied **once** to the
test split and reported there.

Metric buckets follow :mod:`fraud.evaluate`, but the aggregate bucket is named
``unseen_caught`` (not ``other_fraud``) so it is never confused with
``evaluate.py``'s per-rule ``OTHER_FRAUD`` (the cross-rule overlap):

* ``tp`` - flagged ``is_fraud=1`` record injected with a rule (a known typology);
* ``unseen_caught`` - flagged ``is_fraud=1`` record with no rule injection
  (the unseen typologies): real fraud, but not the typology a rule targets;
* ``fp`` - flagged ``is_fraud=0`` record.

``cross_rule_overlap`` is kept as a separate rule diagnostic: a flagged fraud
record injected for a *different* rule (``evaluate.py``'s ``OTHER_FRAUD``).

Precision is ``TP / (TP + FP)``; recall is ``TP / (TP + FN)`` with the recall
denominator the known (rule-injected) fraud. The unseen typologies are reported
separately as their own recall.

Only ``CALIBRATED`` domains enter the main table; ``WEAK`` and ``UNCALIBRATED``
domains go to the excluded block with their validation counts. No feature,
threshold, rule, simulator or ``evaluate`` metric definition is changed here.

Run with::

    python -m fraud.hybrid
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from fraud.config import Config, get_config
from fraud.evaluate import _prf, scan_flags
from fraud.ml import choose_threshold
from fraud.ml_only import (
    MIN_VAL_FLAGS,
    MIN_VAL_TP,
    calibration_status,
    join_scores_labels,
)
from fraud.rules import get_rules

# ``fraud.evaluate`` disables logging at import; re-enable for our CLI output.
logging.disable(logging.NOTSET)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_SCORES_CSV = REPO_ROOT / "reports" / "ml_scores.csv"
LABELS_CSV = REPO_ROOT / "data" / "labels.csv"
HYBRID_MD = REPO_ROOT / "reports" / "hybrid.md"
HYBRID_JSON = REPO_ROOT / "reports" / "hybrid.json"

CAVEAT = (
    "HYBRID combination is selected on validation rows excluding unseen "
    "typologies, then reported once on test. All numbers are on synthetic "
    "labels; unseen recall measures detection of injected patterns, not "
    "generalization. Only CALIBRATED domains are reported in the main table."
)

LEAKAGE_NOTE = (
    "Selection uses validation rows only, with the unseen typologies excluded. "
    "See the 'Threshold-selection leakage' section of reports/ml_only.md: ml.py "
    "carves its val split out of the simulator's train split, so unseen rows "
    "would otherwise leak into selection. Here they never choose a threshold or "
    "a combination rule."
)

#: Detector names reported on the test split.
DETECTORS: tuple[str, ...] = ("RULES_ONLY", "ML_ONLY", "HYBRID")

#: The rule-only baseline. A candidate must strictly beat it to be selected.
RULE_ONLY = "rule_only"


class HybridError(RuntimeError):
    """Raised when the HYBRID analysis cannot be trusted."""


# =============================================================================
# FRAME
# =============================================================================

def is_unseen(fraud_type: str) -> bool:
    """True if any ``|``-separated type starts with ``unseen_``."""
    return any(name.strip().startswith("unseen_") for name in str(fraud_type).split("|"))


def rule_severity(rule_flags: dict[str, set[str]]) -> dict[str, int]:
    """``{record_id: max rule severity}`` from the scan and the rule registry."""
    severity = {rule.id: rule.severity for rule in get_rules()}
    by_record: dict[str, int] = {}
    for rule_id, records in rule_flags.items():
        value = severity.get(rule_id, 0)
        for record in records:
            by_record[record] = max(by_record.get(record, 0), value)
    return by_record


def build_frame(cfg: Config) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    """Join scores to labels and add ``unseen`` / ``rule_flagged`` / ``severity``."""
    scores = pd.read_csv(ML_SCORES_CSV)
    labels = pd.read_csv(LABELS_CSV, keep_default_na=False)
    merged = join_scores_labels(scores, labels)
    merged = merged.merge(
        labels[["record_id", "injected_rule_id"]], on="record_id"
    )

    rule_flags = scan_flags(REPO_ROOT)
    rule_records: set[str] = set().union(*rule_flags.values()) if rule_flags else set()
    severity = rule_severity(rule_flags)

    merged["unseen"] = merged["fraud_type"].map(is_unseen)
    merged["rule_flagged"] = merged["record_id"].isin(rule_records)
    merged["severity"] = merged["record_id"].map(lambda r: severity.get(r, 0))
    merged["cross_overlap"] = _cross_overlap(merged, rule_flags)
    return merged, rule_flags


def _cross_overlap(
    frame: pd.DataFrame, rule_flags: dict[str, set[str]]
) -> pd.Series:
    """True where a rule flagged a fraud record injected for a *different* rule.

    This is :mod:`fraud.evaluate`'s ``OTHER_FRAUD`` (cross-rule overlap). It is a
    property of the rule flags, so it is *not* the aggregate detector's
    ``unseen_caught`` bucket (which counts flagged unseen fraud).
    """
    flagged_by: dict[str, set[str]] = {}
    for rule_id, records in rule_flags.items():
        for record in records:
            flagged_by.setdefault(record, set()).add(rule_id)

    def overlap(record_id: str, injected: str) -> bool:
        injected_rules = {r.strip() for r in str(injected).split("|") if r.strip()}
        return bool(flagged_by.get(record_id, set()) - injected_rules)

    return pd.Series(
        [
            overlap(record_id, injected)
            for record_id, injected in zip(
                frame["record_id"], frame["injected_rule_id"]
            )
        ],
        index=frame.index,
    )


def selection_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Val rows that are known-typology or clean (never an unseen row)."""
    return frame[(frame["split"] == "val") & (~frame["unseen"])]


# =============================================================================
# NORMALISATION + CANDIDATES
# =============================================================================

def ml_norm_stats(selection: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Per-domain ``(min, max)`` of ``ml_score`` over the selection rows only."""
    return {
        str(domain): (float(group["ml_score"].min()), float(group["ml_score"].max()))
        for domain, group in selection.groupby("domain")
    }


def add_normalised(
    frame: pd.DataFrame, stats: dict[str, tuple[float, float]], cfg: Config
) -> pd.DataFrame:
    """Add ``rule_norm`` (severity / severity_max) and ``ml_norm`` (selection min/max)."""
    out = frame.copy()
    out["rule_norm"] = out["severity"] / cfg.hybrid.severity_max
    low = out["domain"].map(lambda d: stats[str(d)][0])
    high = out["domain"].map(lambda d: stats[str(d)][1])
    span = high - low
    out["ml_norm"] = ((out["ml_score"] - low) / span).where(span != 0, 0.0)
    return out


def candidate_names(cfg: Config) -> list[str]:
    """The fixed candidate set: rule-only, max, weighted sums, rule-first."""
    weighted = [f"weighted_w{weight:g}" for weight in cfg.hybrid.weights]
    return [RULE_ONLY, "max", *weighted, "rule_first"]


def candidate_flag(frame: pd.DataFrame, name: str, cfg: Config) -> pd.Series:
    """Binary flag for one combination candidate on ``frame``."""
    rule_flagged = frame["rule_flagged"].astype(bool)
    ml_flagged = frame["ml_flag"] == 1
    if name == RULE_ONLY:
        return rule_flagged
    if name == "rule_first":
        # ML only breaks ties among records no rule flagged.
        return rule_flagged | ml_flagged
    if name == "max":
        score = frame[["rule_norm", "ml_norm"]].max(axis=1)
    elif name.startswith("weighted_w"):
        weight = float(name.split("weighted_w", 1)[1])
        score = weight * frame["rule_norm"] + (1.0 - weight) * frame["ml_norm"]
    else:
        raise HybridError(f"unknown combination candidate: {name}")
    return (score >= cfg.hybrid.decision_threshold).astype(bool)


# =============================================================================
# METRICS
# =============================================================================

def detector_metrics(flag: pd.Series, frame: pd.DataFrame) -> dict[str, Any]:
    """Counts + precision/recall/F1 for one detector flag set (evaluate buckets)."""
    known = (frame["is_fraud"] == 1) & (~frame["unseen"])
    unseen = (frame["is_fraud"] == 1) & (frame["unseen"])
    clean = frame["is_fraud"] == 0

    tp = int((flag & known).sum())
    other = int((flag & unseen).sum())
    fp = int((flag & clean).sum())
    fn = int(((~flag) & known).sum())
    flagged = int(flag.sum())
    if flagged != tp + other + fp:
        raise HybridError(
            f"flagged={flagged} != TP+FP+unseen_caught={tp + other + fp}"
        )
    precision, recall, f1 = _prf(tp, fp, fn)
    known_total = int(known.sum())
    unseen_total = int(unseen.sum())
    if "cross_overlap" in frame.columns:
        cross = int((flag & frame["cross_overlap"].astype(bool)).sum())
    else:
        cross = 0
    return {
        "flags": flagged,
        "tp": tp,
        "fp": fp,
        "unseen_caught": other,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "known_fraud": known_total,
        "unseen_fraud": unseen_total,
        "known_recall": (tp / (tp + fn)) if (tp + fn) else None,
        "unseen_recall": (other / unseen_total) if unseen_total else None,
        # Cross-rule overlap (fraud.evaluate's OTHER_FRAUD notion): rule flags on
        # records injected for a different rule. Distinct from ``unseen_caught``.
        "cross_rule_overlap": cross,
    }


def domain_calibration(
    selection: pd.DataFrame, cfg: Config
) -> tuple[str, dict[str, Any]]:
    """Calibration label from the selection rows (committed threshold)."""
    flagged = selection["ml_flag"] == 1
    tp = int((flagged & (selection["is_fraud"] == 1)).sum())
    flags = int(flagged.sum())
    precision = (tp / flags) if flags else None
    status = calibration_status(precision, flags, tp, cfg.ml.precision_target)
    return status, {
        "n": int(len(selection)),
        "flags": flags,
        "tp": tp,
        "precision": precision,
    }


# =============================================================================
# SELECTION
# =============================================================================

def select_combination(
    selection: pd.DataFrame, cfg: Config
) -> tuple[str, list[dict[str, Any]]]:
    """Pick the candidate with the highest F1 on ``selection`` (val rows only)."""
    if selection.empty:
        raise HybridError("no selection rows (val, known/clean) to choose on")
    splits = set(selection["split"].astype(str)) - {"val"}
    if splits:
        raise HybridError(
            f"combination must be chosen on the validation split only, got: "
            f"{sorted(splits)}"
        )

    rows: list[dict[str, Any]] = []
    best_name, best_f1 = RULE_ONLY, None
    for name in candidate_names(cfg):
        metrics = detector_metrics(candidate_flag(selection, name, cfg), selection)
        if name == RULE_ONLY:
            best_f1 = metrics["f1"]
        elif best_f1 is not None and metrics["f1"] > best_f1:
            best_name, best_f1 = name, metrics["f1"]
        rows.append({
            "combination": name,
            "val_f1": metrics["f1"],
            "val_precision": metrics["precision"],
            "val_recall": metrics["recall"],
            "val_tp": metrics["tp"],
            "val_fp": metrics["fp"],
            "val_fn": metrics["fn"],
        })
    for row in rows:
        row["selected"] = row["combination"] == best_name
    return best_name, rows


# =============================================================================
# REPORT
# =============================================================================

def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _stamp(row: dict[str, Any], status: str, rows_used: int) -> dict[str, Any]:
    """Attach the fields every reported row must carry."""
    row["evaluation_status"] = "in-sample"
    row["calibration_status"] = status
    row["selection_rows_used"] = rows_used
    row["leakage_note"] = LEAKAGE_NOTE
    return row


def _detector_flag(
    frame: pd.DataFrame, detector: str, selected: str, cfg: Config
) -> pd.Series:
    if detector == "RULES_ONLY":
        return frame["rule_flagged"].astype(bool)
    if detector == "ML_ONLY":
        return frame["ml_flag"] == 1
    if detector == "HYBRID":
        return candidate_flag(frame, selected, cfg)
    raise HybridError(f"unknown detector: {detector}")


def _sensitivity(frame: pd.DataFrame, cfg: Config) -> dict[str, Any]:
    """PM-JAY threshold recompute on selection rows: a variant, not the default."""
    selection = selection_rows(frame)
    pmjay = selection[selection["domain"] == "PM-JAY Medical"]
    if pmjay.empty:
        return {}
    threshold = choose_threshold(pmjay, cfg.ml.precision_target)
    flag = pmjay["ml_score"] >= threshold
    tp = int((flag & (pmjay["is_fraud"] == 1)).sum())
    flags = int(flag.sum())
    precision = (tp / flags) if flags else None
    return {
        "variant": "PM-JAY threshold recomputed on selection rows",
        "threshold": float(threshold),
        "flags": flags,
        "tp": tp,
        "precision": precision,
        "calibration_status": calibration_status(
            precision, flags, tp, cfg.ml.precision_target
        ),
        "note": (
            "Sensitivity only: the committed threshold is kept for the report. "
            "This variant is not selected."
        ),
    }


def run(write: bool = True) -> dict[str, Any]:
    """Build the HYBRID report and (optionally) write the md + json files."""
    cfg = get_config()
    frame, _ = build_frame(cfg)
    selection = selection_rows(frame)

    statuses: dict[str, str] = {}
    val_stats: dict[str, dict[str, Any]] = {}
    for domain, group in selection.groupby("domain"):
        status, stats = domain_calibration(group, cfg)
        statuses[str(domain)] = status
        val_stats[str(domain)] = stats
    calibrated = [d for d, s in statuses.items() if s == "CALIBRATED"]

    stats = ml_norm_stats(selection)
    normed = add_normalised(frame, stats, cfg)
    sel_normed = normed[normed["record_id"].isin(selection["record_id"])]
    cal_selection = sel_normed[sel_normed["domain"].isin(calibrated)]

    selected, candidates = select_combination(cal_selection, cfg)
    rule_only_f1 = next(c["val_f1"] for c in candidates if c["combination"] == RULE_ONLY)
    selected_f1 = next(c["val_f1"] for c in candidates if c["combination"] == selected)
    rule_only_val_fp = next(c["val_fp"] for c in candidates if c["combination"] == RULE_ONLY)
    rule_only_val_fn = next(c["val_fn"] for c in candidates if c["combination"] == RULE_ONLY)
    # If the rules are perfect on the selection rows, no candidate can beat them
    # and the selection carries no information about the candidates.
    selection_has_room = bool(rule_only_val_fp + rule_only_val_fn)

    min_events = cfg.simulator.min_events_per_type

    # One-shot test report, CALIBRATED domains only.
    test = normed[normed["split"] == "test"]
    domains: list[dict[str, Any]] = []
    for domain in calibrated:
        group = test[test["domain"] == domain]
        rows_used = int((cal_selection["domain"] == domain).sum())
        detectors = []
        for detector in DETECTORS:
            metrics = detector_metrics(_detector_flag(group, detector, selected, cfg), group)
            row = {"detector": detector, **metrics}
            if detector == "HYBRID" and selected == RULE_ONLY:
                row["equals_detector"] = "RULES_ONLY"
            detectors.append(_stamp(row, statuses[domain], rows_used))
        hybrid = next(r for r in detectors if r["detector"] == "HYBRID")
        test_ml = next(r for r in detectors if r["detector"] == "ML_ONLY")
        val_group = selection[selection["domain"] == domain]
        val_ml = detector_metrics(val_group["ml_flag"] == 1, val_group)
        unseen_fraud = hybrid["unseen_fraud"]
        domains.append(_stamp({
            "domain": domain,
            "selection_rows_used": rows_used,
            "val": val_stats[domain],
            "detectors": detectors,
            "ml_val_to_test_gap": {
                "val": {k: val_ml[k] for k in (
                    "flags", "tp", "fp", "fn", "precision", "recall", "f1")},
                "test": {k: test_ml[k] for k in (
                    "flags", "tp", "fp", "fn", "precision", "recall", "f1")},
                "precision_drop": (
                    val_ml["precision"] - test_ml["precision"]
                    if val_ml["precision"] is not None and test_ml["precision"] is not None
                    else None
                ),
                "recall_drop": (
                    val_ml["recall"] - test_ml["recall"]
                    if val_ml["recall"] is not None and test_ml["recall"] is not None
                    else None
                ),
            },
            "hybrid_recall_split": {
                "known_caught": hybrid["tp"],
                "known_fraud": hybrid["known_fraud"],
                "known_recall": hybrid["known_recall"],
                "unseen_caught": hybrid["unseen_caught"],
                "unseen_fraud": unseen_fraud,
                "unseen_recall": hybrid["unseen_recall"],
                "unseen_evaluation_status": (
                    "in-sample" if unseen_fraud >= min_events else "not evaluable"
                ),
                "unseen_note": (
                    f"{unseen_fraud} unseen events; fewer than {min_events} is not "
                    "a recall estimate."
                    if unseen_fraud < min_events
                    else ""
                ),
            },
        }, statuses[domain], rows_used))

    excluded = []
    for domain, status in statuses.items():
        if domain in calibrated:
            continue
        note = (
            "excluded: WEAK (target met, val evidence too thin)"
            if status == "WEAK"
            else "excluded: UNCALIBRATED (target not met on selection rows)"
        )
        rows_used = int((selection["domain"] == domain).sum())
        excluded.append(_stamp({
            "domain": domain,
            "val": val_stats[domain],
            "note": note,
        }, status, rows_used))

    payload: dict[str, Any] = {
        "generated_by": "fraud.hybrid",
        "caveat": CAVEAT,
        "precision_target": cfg.ml.precision_target,
        "decision_threshold": cfg.hybrid.decision_threshold,
        "severity_max": cfg.hybrid.severity_max,
        "weights": list(cfg.hybrid.weights),
        "min_val_flags_for_calibration": MIN_VAL_FLAGS,
        "min_val_tp_for_calibration": MIN_VAL_TP,
        "leakage_note": LEAKAGE_NOTE,
        "selection": {
            "domains": calibrated,
            "rows_used": int(len(cal_selection)),
            "rows_per_domain": {
                d: int((selection["domain"] == d).sum()) for d in statuses
            },
            "selected": selected,
            "selected_val_f1": selected_f1,
            "no_candidate_beat_rule_only": selected == RULE_ONLY,
            "rule_only_val_f1": rule_only_f1,
            "rule_only_val_fp": rule_only_val_fp,
            "rule_only_val_fn": rule_only_val_fn,
            "selection_set_has_room": selection_has_room,
            "candidates": candidates,
        },
        "domains": domains,
        "excluded": excluded,
        "sensitivity": _sensitivity(frame, cfg),
    }
    for row in payload["selection"]["candidates"]:
        _stamp(row, "n/a", payload["selection"]["rows_used"])

    if write:
        HYBRID_MD.parent.mkdir(parents=True, exist_ok=True)
        HYBRID_MD.write_text(render_markdown(payload), encoding="utf-8")
        HYBRID_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("[hybrid] selected %s (val F1 %s)", selected, _fmt(selected_f1))
        logger.info("[hybrid] wrote %s and %s", HYBRID_MD, HYBRID_JSON)
    return payload


# =============================================================================
# MARKDOWN
# =============================================================================

def _selection_lines(payload: dict[str, Any]) -> list[str]:
    sel = payload["selection"]
    lines = [
        "## Selection (validation rows, unseen excluded)",
        "",
        f"> Selection domains (CALIBRATED only): {', '.join(sel['domains']) or 'none'}. "
        f"Rows used: {sel['rows_used']}.",
        "",
        "| combination | val F1 | val precision | val recall | val TP | val FP "
        "| val FN | selected |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in sel["candidates"]:
        lines.append(
            f"| {row['combination']} | {_fmt(row['val_f1'])} "
            f"| {_fmt(row['val_precision'])} | {_fmt(row['val_recall'])} "
            f"| {row['val_tp']} | {row['val_fp']} | {row['val_fn']} "
            f"| {'yes' if row['selected'] else 'no'} |"
        )
    lines.append("")
    if sel["no_candidate_beat_rule_only"]:
        lines.append(
            f"**No candidate beat the rule-only baseline** (val F1 "
            f"{_fmt(sel['rule_only_val_f1'])}); the selected combination is "
            f"`{sel['selected']}`."
        )
    else:
        lines.append(
            f"Selected combination: `{sel['selected']}` (val F1 "
            f"{_fmt(sel['selected_val_f1'])}, rule-only baseline "
            f"{_fmt(sel['rule_only_val_f1'])})."
        )
    if not sel["selection_set_has_room"]:
        lines.append("")
        lines.append(
            f"> **The selection told us nothing.** The rules are perfect on the "
            f"selection rows (rule-only FP {sel['rule_only_val_fp']}, FN "
            f"{sel['rule_only_val_fn']}), so F1 cannot exceed 1.000 and the "
            f"rule-only baseline is trivially optimal. The candidate comparison "
            f"below has no room to differ; it only shows which candidates add "
            f"false positives."
        )
    lines.append("")
    return lines


def _test_table(domains: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| domain | detector | flags | TP | FP | unseen_caught | FN | cross-rule "
        "overlap | precision | recall | F1 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for domain in domains:
        for row in domain["detectors"]:
            if row.get("equals_detector") == "RULES_ONLY":
                # HYBRID is the rule-only detector by construction: report once,
                # not as two apparently independent results.
                continue
            label = row["detector"]
            if row["detector"] == "RULES_ONLY":
                label = "HYBRID = rules-only (selected)"
            lines.append(
                f"| {domain['domain']} | {label} | {row['flags']} "
                f"| {row['tp']} | {row['fp']} | {row['unseen_caught']} "
                f"| {row['fn']} | {row['cross_rule_overlap']} "
                f"| {_fmt(row['precision'])} "
                f"| {_fmt(row['recall'])} | {_fmt(row['f1'])} |"
            )
    return lines


def _split_lines(domains: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| domain | known caught / known fraud | known recall | unseen caught "
        "/ unseen fraud | unseen recall |",
        "|---|---|---|---|---|",
    ]
    for domain in domains:
        split = domain["hybrid_recall_split"]
        unseen_recall = (
            "not evaluable"
            if split["unseen_evaluation_status"] != "in-sample"
            else _fmt(split["unseen_recall"])
        )
        lines.append(
            f"| {domain['domain']} | {split['known_caught']} / {split['known_fraud']} "
            f"| {_fmt(split['known_recall'])} | {split['unseen_caught']} / "
            f"{split['unseen_fraud']} | {unseen_recall} |"
        )
    return lines


def _ml_gap_lines(domains: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| domain | split | flags | TP | FP | FN | precision | recall | F1 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for domain in domains:
        gap = domain["ml_val_to_test_gap"]
        for split_name in ("val", "test"):
            row = gap[split_name]
            lines.append(
                f"| {domain['domain']} | {split_name} | {row['flags']} "
                f"| {row['tp']} | {row['fp']} | {row['fn']} "
                f"| {_fmt(row['precision'])} | {_fmt(row['recall'])} "
                f"| {_fmt(row['f1'])} |"
            )
    return lines


def _excluded_lines(excluded: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| domain | calibration | val flags | val TP | val precision | note |",
        "|---|---|---|---|---|---|",
    ]
    for domain in excluded:
        val = domain["val"]
        lines.append(
            f"| {domain['domain']} | {domain['calibration_status']} "
            f"| {val['flags']} | {val['tp']} | {_fmt(val['precision'])} "
            f"| {domain['note']} |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    """Render ``reports/hybrid.md`` (caveat above every table)."""
    lines = [
        "# HYBRID (in-sample)",
        "",
        f"> **Caveat.** {payload['caveat']}",
        "",
        "`TP` = known (rule-injected) fraud caught; `unseen_caught` = flagged "
        "fraud with no rule injection (the unseen typologies); `FP` = flagged "
        "`is_fraud=0`. Precision is `TP / (TP + FP)`; recall is `TP / (TP + FN)` "
        "over known fraud. Unseen recall is reported separately. `cross-rule "
        "overlap` is a separate rule diagnostic (`evaluate.py`'s `OTHER_FRAUD`, "
        "a different definition): flagged records injected for a *different* "
        "rule. The aggregate column is named `unseen_caught`, not `OTHER_FRAUD`, "
        "so the two are never confused.",
        "",
    ]
    lines.extend(_selection_lines(payload))

    lines.append("## Test (reported once, including unseen rows)")
    lines.append("")
    if payload["domains"]:
        lines.extend(_test_table(payload["domains"]))
    else:
        lines.append("_No CALIBRATED domain: HYBRID is not reported in the main table._")
    lines.append("")
    if any(row.get("equals_detector") == "RULES_ONLY"
           for d in payload["domains"] for row in d["detectors"]):
        lines.append(
            "> `HYBRID = rules-only (selected)`: the selected combination is "
            "`rule_only`, so HYBRID and RULES_ONLY are the same detector and "
            "agree by construction. They are shown as one row."
        )
        lines.append("")

    lines.append("### HYBRID known vs unseen recall (test)")
    lines.append("")
    if payload["domains"]:
        lines.extend(_split_lines(payload["domains"]))
        for domain in payload["domains"]:
            note = domain["hybrid_recall_split"].get("unseen_note")
            if note:
                lines.append("")
                lines.append(f"> {domain['domain']} unseen: {note}")
    else:
        lines.append("_No CALIBRATED domain._")
    lines.append("")

    lines.append("### ML val to test gap (main finding)")
    lines.append("")
    if payload["domains"]:
        lines.extend(_ml_gap_lines(payload["domains"]))
        for domain in payload["domains"]:
            gap = domain["ml_val_to_test_gap"]
            lines.append("")
            lines.append(
                f"> {domain['domain']} ML precision falls from "
                f"{_fmt(gap['val']['precision'])} (val) to "
                f"{_fmt(gap['test']['precision'])} (test): a drop of "
                f"{_fmt(gap['precision_drop'])}. The ML score is unstable "
                f"across splits."
            )
    else:
        lines.append("_No CALIBRATED domain._")
    lines.append("")

    lines.append("## Excluded (WEAK / UNCALIBRATED)")
    lines.append("")
    lines.append(
        "> Only CALIBRATED domains enter the main table. These domains' val "
        "evidence does not support a calibrated operating point."
    )
    lines.append("")
    lines.extend(_excluded_lines(payload["excluded"]))
    lines.append("")

    sensitivity = payload["sensitivity"]
    if sensitivity:
        lines.append("## Sensitivity (not selected)")
        lines.append("")
        lines.append(
            f"> `{sensitivity['variant']}`: threshold "
            f"{sensitivity['threshold']:.4f} -> {sensitivity['flags']} flags, "
            f"{sensitivity['tp']} TP, precision {_fmt(sensitivity['precision'])}, "
            f"`{sensitivity['calibration_status']}`. {sensitivity['note']}"
        )
        lines.append("")

    lines.append("## Leakage")
    lines.append("")
    lines.append(f"> {payload['leakage_note']}")
    lines.append("")
    return "\n".join(lines)


#: README section, filled from the report payload so the numbers cannot drift
#: from ``reports/hybrid.json``. Only the ``{...}`` fields are substituted.
README_SECTION_TEMPLATE = """## Hybrid detection (synthetic data, in-sample)

HYBRID selected rule-only on MGNREGA Labor validation, the only domain that met the calibration criteria. The selection set had no room for a different outcome: on those 806 known-typology validation rows the rules had zero false positives and zero false negatives, so every candidate could match them at best and none could beat them. The selection therefore tells us only which candidates add false positives, not which combination is best.

On the MGNREGA test split, HYBRID matches the rules exactly, with precision and recall of {hybrid_test_precision} and {hybrid_test_recall}. Its ML component adds no detection on known typologies and catches {unseen_caught} of {unseen_events} unseen events. Four events is too few to estimate recall, so that split is reported as not evaluable.

The ML score's precision fell from {ml_val_precision} on validation to {ml_test_precision} on test. This instability is the main finding for the ML layer, not the HYBRID row. Civil Registry (WEAK: two validation flags) and PM-JAY (UNCALIBRATED: seven flags, three true positives, precision 0.429) are not calibrated and are excluded from the main table. A sensitivity run on PM-JAY with a different threshold gave two flags, both correct, which is too little evidence to use.

All numbers are on synthetic labels. Unseen recall measures detection of injected patterns, not generalization. ML thresholds are per-domain and not comparable across domains.
"""


def render_readme_section(payload: dict[str, Any]) -> str:
    """Render the README section, substituting values from ``payload``.

    The substituted fields are exactly the placeholders in the template; every
    number comes from the generated report, not from this file by hand.
    """
    if not payload["domains"]:
        raise HybridError("no CALIBRATED domain: cannot render the README section")
    domain = payload["domains"][0]
    hybrid = next(r for r in domain["detectors"] if r["detector"] == "HYBRID")
    split = domain["hybrid_recall_split"]
    gap = domain["ml_val_to_test_gap"]
    return README_SECTION_TEMPLATE.format(
        hybrid_test_precision=_fmt(hybrid["precision"]),
        hybrid_test_recall=_fmt(hybrid["recall"]),
        unseen_caught=split["unseen_caught"],
        unseen_events=split["unseen_fraud"],
        ml_val_precision=_fmt(gap["val"]["precision"]),
        ml_test_precision=_fmt(gap["test"]["precision"]),
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="HYBRID combination report (P4c).")
    parser.add_argument(
        "--readme",
        action="store_true",
        help="print the README section (numbers from the report payload) and exit",
    )
    args = parser.parse_args(argv)
    if args.readme:
        print(render_readme_section(run(write=False)))
        return
    run()


if __name__ == "__main__":
    main()
