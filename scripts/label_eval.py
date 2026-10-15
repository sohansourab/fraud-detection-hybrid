#!/usr/bin/env python3
"""Read-only rule-vs-labels audit (module P2b).

Runs the detection rules over ``data/`` and joins the flags against the
synthetic ground truth in ``data/labels.csv``. Prints per-rule flag counts and,
for the rules exercised by the P2a injections (013/017/021), precision/recall.

This is a standalone analysis script: labels are never imported into detection
code (``src/fraud/rules/*`` or ``src/fraud/pipeline.py``).
"""
from __future__ import annotations

import contextlib
import io
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

import audit_scanner  # noqa: E402

LABELS_PATH = REPO_ROOT / "data" / "labels.csv"
DETAIL_RULES = ("RULE_013", "RULE_017", "RULE_021")


def scan_flags() -> dict[str, set[str]]:
    """Run the scanner and return ``{rule_id: set(record_id)}``."""
    with contextlib.redirect_stdout(io.StringIO()):
        scanner = audit_scanner.MasterFraudScanner()
        scanner.run_all_scans()
    flags: dict[str, set[str]] = {}
    for report in scanner.all_reports:
        for flag in report.flags:
            flags.setdefault(flag["rule_id"], set()).add(report.record_id)
    return flags


def ground_truth() -> dict[str, set[str]]:
    """``{rule_id: set(record_id)}`` from labels, plus ``_hard_negative``."""
    labels = pd.read_csv(LABELS_PATH, keep_default_na=False)
    truth: dict[str, set[str]] = {}
    for record_id, rule_ids in zip(labels["record_id"], labels["injected_rule_id"]):
        for rule_id in str(rule_ids).split("|"):
            if rule_id:
                truth.setdefault(rule_id, set()).add(record_id)
    truth["_hard_negative"] = set(
        labels.loc[
            labels["fraud_type"] == "hard_negative_blank_mobile", "record_id"
        ]
    )
    return truth


def main() -> None:
    flags = scan_flags()
    truth = ground_truth()

    print("Per-rule flags (all rules):")
    for rule_id in sorted(flags):
        print(f"  {rule_id:9s} {len(flags[rule_id]):5d}")

    print("\nRules exercised by the P2a injections (precision vs labels.csv):")
    header = f"  {'rule':9s} {'flags':>6s} {'TP':>5s} {'FP':>5s} {'FN':>5s} {'precision':>10s} {'recall':>7s}"
    print(header)
    for rule_id in DETAIL_RULES:
        flagged = flags.get(rule_id, set())
        pos = truth.get(rule_id, set())
        tp = len(flagged & pos)
        fp = len(flagged - pos)
        fn = len(pos - flagged)
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        print(
            f"  {rule_id:9s} {len(flagged):6d} {tp:5d} {fp:5d} {fn:5d} "
            f"{precision:10.2f} {recall:7.2f}"
        )

    hn_flagged = len(flags.get("RULE_013", set()) & truth["_hard_negative"])
    print(
        f"\nRULE_013 flags on hard_negative_blank_mobile records: {hn_flagged} (expected 0)"
    )


if __name__ == "__main__":
    main()
