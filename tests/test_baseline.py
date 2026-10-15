"""Regression guard: config extraction must not change detection output.

Re-runs the scanner and asserts the flagged record ids per rule match the
snapshot captured *before* the refactor (``baseline/flags_before.json``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import audit_scanner  # noqa: E402

BASELINE_PATH = Path(__file__).resolve().parent / "baseline" / "flags_before.json"


def _run_scanner() -> tuple[dict[str, list[str]], int, int]:
    """Return (flags_by_rule, total_flag_count, flagged_record_count)."""
    scanner = audit_scanner.MasterFraudScanner()
    scanner.run_all_scans()

    flags_by_rule: dict[str, list[str]] = {}
    total_flags = 0
    for report in scanner.all_reports:
        for flag in report.flags:
            flags_by_rule.setdefault(flag["rule_id"], []).append(report.record_id)
            total_flags += 1
    return flags_by_rule, total_flags, len(scanner.all_reports)


def test_baseline_flags_unchanged() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    rule_ids = [key for key in baseline if not key.startswith("_")]

    flags_by_rule, total_flags, flagged_records = _run_scanner()

    assert total_flags == baseline["_total_flag_count"]
    assert flagged_records == baseline["_total_flagged_records"]

    for rule_id in rule_ids:
        assert sorted(flags_by_rule.get(rule_id, [])) == baseline[rule_id], rule_id

    # No rule that was empty/unseen at baseline may silently appear.
    assert set(flags_by_rule) <= set(rule_ids)
