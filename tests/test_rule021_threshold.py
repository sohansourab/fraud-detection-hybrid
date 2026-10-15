"""Regression test for Rule 021 (procedure mill).

Bug fixed in P1d: the rule computed per (hospital, procedure, month) counts
but never compared them to ``PROCEDURE_MILL_THRESHOLD``, so it could never
fire. It also mutated the input frame by adding an ``AdmissionMonth`` column.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.config import get_config  # noqa: E402
from fraud.rules.pmjay import ProcedureMillRule  # noqa: E402


def test_procedure_mill_fires_above_threshold_without_mutating_input() -> None:
    cfg = get_config()
    n = cfg.pmjay.procedure_mill_threshold + 1
    df = pd.DataFrame({
        "ClaimID": [f"CLM_{i:04d}" for i in range(n)],
        "AdmissionDate": pd.to_datetime(["2024-01-05"] * n),
        "HospitalID": ["HOSP_001"] * n,
        "ProcedureName": ["Cataract Surgery"] * n,
    })
    before = df.copy(deep=True)

    result = ProcedureMillRule().evaluate({"pmjay": df}, cfg)

    assert len(result) == n
    pd.testing.assert_frame_equal(df, before)  # input not mutated
