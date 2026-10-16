"""ML-only caught analysis (module P4b).

Joins the P4a record-level scores (``reports/ml_scores.csv``) to the simulator
labels and to the rule flags, and reports how many fraud records the ML layer
catches that **no rule** flagged (``ML_ONLY_CAUGHT``). Analysis and reporting
only: no feature, threshold, rule or simulator change.

Rule flags are read with :func:`fraud.evaluate.scan_flags` so the definitions
match the P3 evaluator exactly.

Calibration (read from the P4a output) is a label on every row:

* ``CALIBRATED`` - val precision >= target and val flags >= 10 and val TP >= 3;
* ``WEAK`` - target met, but the val evidence is too thin to call it calibrated;
* ``UNCALIBRATED`` - target not met (the P4a fallback was used).

ML scores exist only for prevalence 0.02 (P4a wrote a single ``ml_scores.csv``);
0.05/0.10 have different raw features and record sets, so they are marked
``not evaluable`` rather than scored with the wrong thresholds.

``ML_ONLY_CAUGHT`` is split into KNOWN (``fraud_type`` with no ``unseen_*``
token) and UNSEEN (``fraud_type`` with an ``unseen_*`` token); UNSEEN is broken
out by typology, and a type under ``simulator.min_events_per_type`` is marked
``not evaluable``. PM-JAY is pinned out of the main table while its calibration
rests on the injected patterns.

The report also carries a threshold-selection leakage diagnostic: ``ml.py``
carves val out of the simulator's ``train`` split, so injected unseen rows can
land in the val set that chooses the threshold. That is reported, not fixed.

Run with::

    python -m fraud.ml_only
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from fraud.config import Config, get_config
from fraud.evaluate import scan_flags

# ``fraud.evaluate`` disables logging at import; re-enable for our CLI output.
logging.disable(logging.NOTSET)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_SCORES_CSV = REPO_ROOT / "reports" / "ml_scores.csv"
LABELS_CSV = REPO_ROOT / "data" / "labels.csv"
ML_ONLY_MD = REPO_ROOT / "reports" / "ml_only.md"
ML_ONLY_JSON = REPO_ROOT / "reports" / "ml_only.json"

#: Levels reported by the harness; only 0.02 has ML scores in this module.
LEVELS: tuple[str, ...] = ("0.02", "0.05", "0.10")
ML_LEVEL = "0.02"

MIN_VAL_FLAGS = 10
MIN_VAL_TP = 3

#: A recall estimate from fewer caught records than this is too thin to report.
MIN_CAUGHT_FOR_RECALL = 3

#: Status for an unseen typology that this domain never injected.
NO_UNSEEN = "no unseen events injected"

CAVEAT = (
    "Scores are on synthetic labels. The UNSEEN patterns were injected by the "
    "same simulator that generated the labels, so UNSEEN recall measures "
    "detection of our injected patterns, not generalization. ML thresholds are "
    "per-domain and not comparable across domains. A WEAK domain's numbers are "
    "not a calibrated result."
)

#: The three unseen typologies (module P2e). Every row carries its own events
#: count; a type below ``simulator.min_events_per_type`` is not evaluable.
UNSEEN_TYPES: tuple[str, ...] = (
    "unseen_just_under_limit",
    "unseen_weekend_cluster",
    "unseen_growing_amounts",
)

#: Domains pinned out of the main comparison table. PM-JAY's calibrated status
#: now rests on the injected (unseen) patterns, so it stays excluded until P4c
#: explains why it should count.
PINNED_EXCLUDED = {"PM-JAY Medical"}
PINNED_EXCLUDED_NOTE = (
    "excluded: calibration rests on injected (unseen) patterns; see P4c"
)


class MLError(RuntimeError):
    """Raised when the ML-only analysis cannot be trusted."""


# =============================================================================
# CALIBRATION
# =============================================================================

def calibration_status(
    val_precision: float | None, val_flags: int, val_tp: int, target: float
) -> str:
    """Label a domain from its validation evidence (see module docstring)."""
    if val_precision is None or val_precision < target:
        return "UNCALIBRATED"
    if val_flags >= MIN_VAL_FLAGS and val_tp >= MIN_VAL_TP:
        return "CALIBRATED"
    return "WEAK"


# =============================================================================
# JOIN
# =============================================================================

def join_scores_labels(scores: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """1:1 join by ``record_id``; fail loudly on any duplicate or mismatch."""
    for name, frame in (("ml_scores", scores), ("labels", labels)):
        duplicated = frame.loc[frame["record_id"].duplicated(), "record_id"].unique()
        if len(duplicated):
            raise MLError(
                f"{name} has duplicate record_id(s): {list(duplicated[:5])}"
            )

    merged = scores.merge(
        labels[["record_id", "is_fraud", "fraud_type"]],
        on="record_id",
        how="outer",
        indicator=True,
    )
    unmatched = merged[merged["_merge"] != "both"]
    if len(unmatched):
        raise MLError(
            f"{len(unmatched)} record(s) do not match exactly one label and one "
            f"ml row: {unmatched['record_id'].head(5).tolist()}"
        )
    merged["is_fraud"] = merged["is_fraud"].astype(int)
    return merged.drop(columns=["_merge"])


# =============================================================================
# COUNTS
# =============================================================================

def split_stats(frame: pd.DataFrame) -> dict[str, Any]:
    """Flag/fraud counts and precision/recall for one split."""
    flags = int((frame["ml_flag"] == 1).sum())
    positives = int((frame["is_fraud"] == 1).sum())
    tp = int(((frame["ml_flag"] == 1) & (frame["is_fraud"] == 1)).sum())
    return {
        "n": int(len(frame)),
        "fraud": positives,
        "flags": flags,
        "tp": tp,
        "precision": (tp / flags) if flags else None,
        "recall": (tp / positives) if positives else None,
    }


def ml_only_stats(frame: pd.DataFrame, rule_records: set[str]) -> dict[str, int]:
    """ML flags, rule flags, ML-only flags and ``ML_ONLY_CAUGHT``."""
    rule_flagged = frame["record_id"].isin(rule_records)
    ml_flagged = frame["ml_flag"] == 1
    ml_only = ml_flagged & ~rule_flagged
    caught = ml_only & (frame["is_fraud"] == 1)
    return {
        "ml_flags": int(ml_flagged.sum()),
        "rule_flags": int(rule_flagged.sum()),
        "ml_only_flags": int(ml_only.sum()),
        "ml_only_caught": int(caught.sum()),
    }


def _types(series: pd.Series) -> dict[str, int]:
    """Count records per ``fraud_type`` (multi-injection ``A|B`` split)."""
    counts: dict[str, int] = {}
    for value in series.astype(str):
        for name in value.split("|"):
            name = name.strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def caught_by_type(
    frame: pd.DataFrame, rule_records: set[str], min_events: int
) -> list[dict[str, Any]]:
    """``ML_ONLY_CAUGHT`` per fraud type, with thin types marked not evaluable."""
    fraud = frame[frame["is_fraud"] == 1]
    events = _types(fraud["fraud_type"])
    caught = fraud[
        (fraud["ml_flag"] == 1) & (~fraud["record_id"].isin(rule_records))
    ]
    caught_counts = _types(caught["fraud_type"])

    rows: list[dict[str, Any]] = []
    for name in sorted(set(events) | set(caught_counts)):
        event_count = events.get(name, 0)
        rows.append({
            "fraud_type": name,
            "events": event_count,
            "ml_only_caught": caught_counts.get(name, 0),
            "evaluation_status": (
                "in-sample" if event_count >= min_events else "not evaluable"
            ),
        })
    return rows


def _has_unseen(fraud_type: str) -> bool:
    """True if any ``|``-separated type starts with ``unseen_``."""
    return any(name.strip().startswith("unseen_") for name in str(fraud_type).split("|"))


def _has_type(fraud_type: str, target: str) -> bool:
    """True if ``target`` is one of the ``|``-separated types."""
    return target in [name.strip() for name in str(fraud_type).split("|")]


def _events_status(event_count: int, min_events: int) -> str:
    """Status of an unseen typology from its injected event count."""
    if event_count == 0:
        return NO_UNSEEN
    return "in-sample" if event_count >= min_events else "not evaluable"


def _recall_note(caught: int, events: int) -> str:
    """Human note on the caught count; never a generalization claim."""
    if events == 0:
        return "no unseen events injected for this domain"
    if caught < MIN_CAUGHT_FOR_RECALL:
        return f"{caught} of {events}, not evaluable as a recall estimate"
    return (
        f"{caught} of {events}, in-sample (injected patterns; not a "
        "generalization estimate)"
    )


def caught_split(
    frame: pd.DataFrame, rule_records: set[str], min_events: int
) -> dict[str, Any]:
    """Split ``ML_ONLY_CAUGHT`` into KNOWN and UNSEEN, then UNSEEN by type.

    KNOWN + UNSEEN == ``ml_only_caught`` by construction: every caught record
    is classified by whether any of its ``fraud_type`` tokens is ``unseen_*``.
    """
    fraud = frame[frame["is_fraud"] == 1]
    caught = fraud[
        (fraud["ml_flag"] == 1) & (~fraud["record_id"].isin(rule_records))
    ]
    unseen_mask = caught["fraud_type"].map(_has_unseen).astype(bool)
    unseen_caught = caught[unseen_mask]
    events = _types(fraud["fraud_type"])

    by_type = []
    for name in UNSEEN_TYPES:
        event_count = events.get(name, 0)
        caught_count = int(
            unseen_caught["fraud_type"]
            .map(lambda v, wanted=name: _has_type(v, wanted))
            .astype(bool)
            .sum()
        )
        by_type.append({
            "fraud_type": name,
            "events": event_count,
            "ml_only_caught": caught_count,
            "evaluation_status": _events_status(event_count, min_events),
            "recall_note": _recall_note(caught_count, event_count),
        })
    return {
        "ml_only_caught_known": int((~unseen_mask).sum()),
        "ml_only_caught_unseen": int(unseen_mask.sum()),
        "unseen_by_type": by_type,
    }


def leakage_check(frame: pd.DataFrame) -> dict[str, Any]:
    """Whether the val split (threshold selection) contains unseen rows.

    ``ml.py`` carves its val split out of the simulator's ``train`` split, so an
    injected unseen record that the simulator put in ``train`` can land in the
    val set whose precision chooses the threshold. That is leakage: the same
    typology we report UNSEEN recall on helped pick the operating point.
    """
    val = frame[frame["split"] == "val"]
    unseen = val["fraud_type"].map(_has_unseen).astype(bool)
    flagged = val["ml_flag"] == 1
    fraud = val["is_fraud"] == 1
    val_unseen = int(unseen.sum())
    flags_excl = int((flagged & ~unseen).sum())
    tp_excl = int((fraud & flagged & ~unseen).sum())
    return {
        "val_unseen": val_unseen,
        "val_unseen_flagged": int((unseen & flagged).sum()),
        "val_flags_excl_unseen": flags_excl,
        "val_tp_excl_unseen": tp_excl,
        "val_precision_excl_unseen": (tp_excl / flags_excl) if flags_excl else None,
        "leaks": val_unseen > 0,
    }


def evaluate_domain(
    frame: pd.DataFrame, rule_records: set[str], cfg: Config
) -> dict[str, Any]:
    """One domain's calibration, counts and per-type breakdown."""
    val = split_stats(frame[frame["split"] == "val"])
    status = calibration_status(
        val["precision"], val["flags"], val["tp"], cfg.ml.precision_target
    )
    split = caught_split(frame, rule_records, cfg.simulator.min_events_per_type)
    for row in split["unseen_by_type"]:
        row["calibration_status"] = status
    return {
        "domain": str(frame["domain"].iloc[0]),
        "calibration_status": status,
        "evaluation_status": "in-sample",
        **ml_only_stats(frame, rule_records),
        **split,
        "leakage": leakage_check(frame),
        "val": val,
        "test": split_stats(frame[frame["split"] == "test"]),
        "by_fraud_type": caught_by_type(
            frame, rule_records, cfg.simulator.min_events_per_type
        ),
    }


# =============================================================================
# REPORT
# =============================================================================

def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _main_table(domains: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| domain | calibration | status | ML flags | rule flags | ML-only flags "
        "| ML_ONLY_CAUGHT | KNOWN | UNSEEN | val flags | val TP | val prec | val rec "
        "| test flags | test TP | test prec | test rec |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for d in domains:
        val, test = d["val"], d["test"]
        lines.append(
            f"| {d['domain']} | {d['calibration_status']} | {d['evaluation_status']} "
            f"| {d['ml_flags']} | {d['rule_flags']} | {d['ml_only_flags']} "
            f"| {d['ml_only_caught']} | {d['ml_only_caught_known']} "
            f"| {d['ml_only_caught_unseen']} | {val['flags']} | {val['tp']} "
            f"| {_fmt(val['precision'])} | {_fmt(val['recall'])} | {test['flags']} "
            f"| {test['tp']} | {_fmt(test['precision'])} | {_fmt(test['recall'])} |"
        )
    return lines


def _type_table(domain: dict[str, Any]) -> list[str]:
    lines = [
        f"### ML_ONLY_CAUGHT by fraud_type - {domain['domain']} "
        f"({domain['calibration_status']})",
        "",
        "| fraud_type | events | ML_ONLY_CAUGHT | status |",
        "|---|---|---|---|",
    ]
    for row in domain["by_fraud_type"]:
        lines.append(
            f"| {row['fraud_type']} | {row['events']} | {row['ml_only_caught']} "
            f"| {row['evaluation_status']} |"
        )
    return lines


def _split_table(domain: dict[str, Any]) -> list[str]:
    """KNOWN vs UNSEEN split, then the UNSEEN typologies by events."""
    lines = [
        f"### ML_ONLY_CAUGHT: KNOWN vs UNSEEN - {domain['domain']} "
        f"({domain['calibration_status']})",
        "",
        "| group | ML_ONLY_CAUGHT | status |",
        "|---|---|---|",
        f"| KNOWN | {domain['ml_only_caught_known']} | {domain['evaluation_status']} |",
        f"| UNSEEN | {domain['ml_only_caught_unseen']} | {domain['evaluation_status']} |",
        f"| total | {domain['ml_only_caught']} | {domain['evaluation_status']} |",
        "",
        "| unseen_type | events | ML_ONLY_CAUGHT | status | note |",
        "|---|---|---|---|---|",
    ]
    for row in domain["unseen_by_type"]:
        lines.append(
            f"| {row['fraud_type']} | {row['events']} | {row['ml_only_caught']} "
            f"| {row['evaluation_status']} | {row['recall_note']} |"
        )
    return lines


def _leakage_table(domains: list[dict[str, Any]], target: float) -> list[str]:
    """Per-domain val-leakage diagnostic (unseen rows in the threshold split)."""
    lines = [
        "| domain | val unseen | val unseen flagged | val flags excl unseen "
        "| val TP excl unseen | val prec excl unseen | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in domains:
        leak = d["leakage"]
        prec = leak["val_precision_excl_unseen"]
        if leak["leaks"]:
            note = (
                f"{leak['val_unseen']} unseen in val "
                f"({leak['val_unseen_flagged']} flagged); excluding them val "
                f"precision is {_fmt(prec)}"
            )
            if prec is not None and prec < target:
                note += f" (< {target:g} target), so the label rests on the injected rows"
        else:
            note = "no unseen rows in val (threshold not selected on unseen)"
        lines.append(
            f"| {d['domain']} | {leak['val_unseen']} | {leak['val_unseen_flagged']} "
            f"| {leak['val_flags_excl_unseen']} | {leak['val_tp_excl_unseen']} "
            f"| {_fmt(prec)} | {note} |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    """Render ``reports/ml_only.md`` (caveat above every table)."""
    lines = [
        "# ML-only caught (in-sample)",
        "",
        f"> **Caveat.** {payload['caveat']}",
        "",
        "`ML_ONLY_CAUGHT` = `is_fraud=1` and ML flagged and **no rule** flagged "
        "the record. It is not a claim that ML is good: it counts only what the "
        "rules miss. Calibration is a label on the row, not a gate.",
        "",
    ]

    level = payload["levels"][ML_LEVEL]
    lines.append(f"## Prevalence {ML_LEVEL} (in-sample)")
    lines.append("")
    lines.append(
        "> Scored against synthetic labels; not a generalization estimate. "
        "Thresholds are per-domain and not comparable across domains."
    )
    lines.append("")
    lines.extend(_main_table(level["domains"]))
    lines.append("")
    for domain in level["domains"]:
        lines.extend(_type_table(domain))
        lines.append("")
        lines.extend(_split_table(domain))
        lines.append("")

    lines.append("## Excluded from the main table")
    lines.append("")
    lines.append(
        "> Reported for completeness only; these domains are not part of the "
        "main comparison. A pinned domain's note says why."
    )
    lines.append("")
    lines.append(
        "| domain | calibration | status | ML flags | ML_ONLY_CAUGHT | KNOWN "
        "| UNSEEN | note |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for domain in level["excluded"]:
        lines.append(
            f"| {domain['domain']} | {domain['calibration_status']} "
            f"| {domain['evaluation_status']} | {domain['ml_flags']} "
            f"| {domain['ml_only_caught']} | {domain['ml_only_caught_known']} "
            f"| {domain['ml_only_caught_unseen']} | {domain['note']} |"
        )
    lines.append("")
    for domain in level["excluded"]:
        lines.extend(_split_table(domain))
        lines.append("")

    lines.append("## Threshold-selection leakage (unseen rows in val)")
    lines.append("")
    lines.append(
        "> `ml.py` carves its val split out of the simulator's `train` split, so "
        "an injected unseen record that the simulator put in `train` can land in "
        "the val set whose precision chooses the threshold. That is leakage: the "
        "same typology we report UNSEEN recall on helped pick the operating "
        "point. The counts below are the evidence."
    )
    lines.append("")
    lines.extend(
        _leakage_table(
            level["domains"] + level["excluded"], payload["precision_target"]
        )
    )
    lines.append("")

    lines.append("## Not evaluated")
    lines.append("")
    for name in LEVELS:
        if name == ML_LEVEL:
            continue
        entry = payload["levels"][name]
        lines.append(f"- {name}: {entry['evaluation_status']} - {entry['reason']}")
    lines.append("")
    return "\n".join(lines)


def run(write: bool = True) -> dict[str, Any]:
    """Build the ML-only report and (optionally) write the md + json files."""
    cfg = get_config()
    scores = pd.read_csv(ML_SCORES_CSV)
    labels = pd.read_csv(LABELS_CSV, keep_default_na=False)
    merged = join_scores_labels(scores, labels)

    rule_flags = scan_flags(REPO_ROOT)
    rule_records: set[str] = set().union(*rule_flags.values()) if rule_flags else set()

    domains: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for domain_name in merged["domain"].unique():
        report = evaluate_domain(merged[merged["domain"] == domain_name], rule_records, cfg)
        if report["domain"] in PINNED_EXCLUDED:
            report["note"] = PINNED_EXCLUDED_NOTE
            excluded.append(report)
        elif report["calibration_status"] == "UNCALIBRATED":
            report["note"] = "excluded: no calibrated threshold"
            excluded.append(report)
        else:
            domains.append(report)
        logger.info(
            "[ml_only] %s: calibration=%s ml_flags=%d ml_only_caught=%d",
            report["domain"], report["calibration_status"],
            report["ml_flags"], report["ml_only_caught"],
        )

    payload: dict[str, Any] = {
        "generated_by": "fraud.ml_only",
        "caveat": CAVEAT,
        "precision_target": cfg.ml.precision_target,
        "min_events_per_type": cfg.simulator.min_events_per_type,
        "min_val_flags_for_calibration": MIN_VAL_FLAGS,
        "min_val_tp_for_calibration": MIN_VAL_TP,
        "levels": {
            ML_LEVEL: {
                "evaluation_status": "in-sample",
                "domains": domains,
                "excluded": excluded,
            },
        },
    }
    for name in LEVELS:
        if name == ML_LEVEL:
            continue
        payload["levels"][name] = {
            "evaluation_status": "not evaluable",
            "reason": (
                "no ML scores at this prevalence (P4a wrote 0.02 only; the raw "
                "features and record sets differ, so re-scoring would need new "
                "per-level thresholds, which P4b must not add)"
            ),
        }

    if write:
        ML_ONLY_MD.parent.mkdir(parents=True, exist_ok=True)
        ML_ONLY_MD.write_text(render_markdown(payload), encoding="utf-8")
        ML_ONLY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("[ml_only] wrote %s and %s", ML_ONLY_MD, ML_ONLY_JSON)
    return payload


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="ML-only caught analysis (P4b).")
    parser.parse_args(argv)
    run()


if __name__ == "__main__":
    main()
