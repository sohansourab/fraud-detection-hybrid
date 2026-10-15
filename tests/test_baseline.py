"""Regression guard for detection output.

Re-runs the scanner and asserts the flagged record ids per rule match the
current snapshot (``baseline/flags_after_p1d.json``). The snapshot also records
an MD5 of every input table: if the data has changed, the test fails with a
"regenerate deliberately" message instead of a confusing flag diff.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import audit_scanner  # noqa: E402
from fraud.config import get_config  # noqa: E402

BASELINE_PATH = Path(__file__).resolve().parent / "baseline" / "flags_after_p1d.json"


def _input_md5s() -> dict[str, str]:
    """MD5 of each scanner input table, mirroring scripts/make_baseline.py."""
    cfg = get_config()
    hashes: dict[str, str] = {}
    for name in ("beneficiaries", "mgnrega", "pmjay"):
        path = Path(getattr(cfg.paths, name))
        if not path.is_absolute():
            path = REPO_ROOT / path
        hashes[name] = (
            hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        )
    return hashes


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

    expected_md5 = baseline.get("_input_md5")
    if expected_md5:
        current_md5 = _input_md5s()
        changed = [name for name in expected_md5 if expected_md5[name] != current_md5.get(name)]
        if changed:
            raise AssertionError(
                "Input data changed since the baseline snapshot was recorded "
                f"({', '.join(sorted(changed))}). Flag output is expected to differ. "
                "If this change is intentional, regenerate the snapshot deliberately:\n"
                "    python data_simulator.py && python scripts/make_baseline.py"
            )

    rule_ids = [key for key in baseline if not key.startswith("_")]

    flags_by_rule, total_flags, flagged_records = _run_scanner()

    assert total_flags == baseline["_total_flag_count"]
    assert flagged_records == baseline["_total_flagged_records"]

    for rule_id in rule_ids:
        assert sorted(flags_by_rule.get(rule_id, [])) == baseline[rule_id], rule_id

    # No rule that was empty/unseen at baseline may silently appear.
    assert set(flags_by_rule) <= set(rule_ids)
