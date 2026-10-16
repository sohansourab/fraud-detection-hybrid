#!/usr/bin/env python3
"""Regenerate a per-rule flag-id snapshot used by the baseline regression test.

Usage::

    python scripts/make_baseline.py [output_path]

Default output: ``tests/baseline/flags_after_p1d.json``.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

logging.disable(logging.CRITICAL)

import audit_scanner  # noqa: E402
from fraud.config import get_config  # noqa: E402
from fraud.rules import get_rules  # noqa: E402

INPUT_TABLES = ("beneficiaries", "mgnrega", "pmjay")


def input_md5s() -> dict[str, str]:
    """MD5 of each scanner input table, keyed by config path name."""
    cfg = get_config()
    hashes: dict[str, str] = {}
    for name in INPUT_TABLES:
        path = Path(getattr(cfg.paths, name))
        if not path.is_absolute():
            path = REPO_ROOT / path
        hashes[name] = (
            hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        )
    return hashes


def snapshot() -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        scanner = audit_scanner.MasterFraudScanner()
        scanner.run_all_scans()

    rules: dict[str, list[str]] = {}
    total_flags = 0
    for report in scanner.all_reports:
        for flag in report.flags:
            rules.setdefault(flag["rule_id"], []).append(report.record_id)
            total_flags += 1

    for rule in get_rules():
        rules.setdefault(rule.id, [])

    out = {
        "_total_flag_count": total_flags,
        "_total_flagged_records": len(scanner.all_reports),
        "_input_md5": input_md5s(),
    }
    for rule_id in sorted(rules):
        out[rule_id] = sorted(rules[rule_id])
    return out


def main() -> None:
    dest = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPO_ROOT / "tests" / "baseline" / "flags_after_p1d.json"
    )
    dest.write_text(json.dumps(snapshot(), indent=2), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
