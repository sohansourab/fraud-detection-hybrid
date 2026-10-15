#!/usr/bin/env python3
"""Micro-benchmark: time each fraud rule and the full scan.

Usage:
    python scripts/bench.py

Notes:
    The dataset here is small (~10k source rows, ~1.8k flagged), so per-rule
    times are milliseconds and dominated by fixed overhead. The point of this
    benchmark is to confirm that vectorization removed the per-row Python
    loops; it is not a large-N throughput test.
"""
from __future__ import annotations

import contextlib
import io
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

import audit_scanner  # noqa: E402
from fraud.config import get_config  # noqa: E402
from fraud.rules import get_rules  # noqa: E402

REPEATS = 3


def _quiet() -> contextlib.AbstractContextManager:
    return contextlib.redirect_stdout(io.StringIO())


def _flagged_frame(reports) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"record_id": r.record_id, "domain": r.domain, "record_name": r.record_name}
            for r in reports
        ],
        columns=["record_id", "domain", "record_name"],
    )


def main() -> None:
    cfg = get_config()
    rules = get_rules()

    # Populate flagged_records so the cross-domain rule has its input.
    with _quiet():
        warmup = audit_scanner.MasterFraudScanner()
        warmup.run_all_scans()
    tables = audit_scanner.load_tables()
    tables["flagged_records"] = _flagged_frame(warmup.all_reports)

    print(f"{'rule':<10} {'name':<26} {'flags':>7} {'best ms':>9}")
    print("-" * 56)

    total = 0.0
    for rule in rules:
        best = float("inf")
        flags = 0
        for _ in range(REPEATS):
            start = time.perf_counter()
            result = rule.evaluate(tables, cfg)
            best = min(best, time.perf_counter() - start)
            flags = len(result)
        total += best
        print(f"{rule.id:<10} {rule.name:<26} {flags:>7} {best * 1000:>9.2f}")

    print("-" * 56)
    print(f"{'TOTAL rules':<37} {'':>7} {total * 1000:>9.2f} ms")

    best_full = float("inf")
    scanner = audit_scanner.MasterFraudScanner()
    for _ in range(REPEATS):
        start = time.perf_counter()
        with _quiet():
            scanner = audit_scanner.MasterFraudScanner()
            scanner.run_all_scans()
        best_full = min(best_full, time.perf_counter() - start)
    print(f"{'FULL run_all_scans':<37} {len(scanner.all_reports):>7} {best_full * 1000:>9.2f} ms")


if __name__ == "__main__":
    main()
