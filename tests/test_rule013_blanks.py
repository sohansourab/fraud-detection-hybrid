"""Regression tests for Rule 013 (clone detection / shared mobile).

Bug fixed in P1d: null/blank mobile numbers were stringified to "nan"/"" and
then counted as a shared mobile, producing false positives.
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
from fraud.rules.civil import CloneDetectionRule  # noqa: E402


def test_blank_or_null_mobiles_are_not_shared() -> None:
    """Before the fix these four ""/NaN rows exceeded the sharing limit."""
    cfg = get_config()
    df = pd.DataFrame({
        "BeneficiaryID": [f"BEN_{i}" for i in range(6)],
        "MobileNumber": ["", "", "", "nan", None, cfg.civil_registry.dummy_mobile],
    })
    result = CloneDetectionRule().evaluate({"beneficiaries": df}, cfg)
    assert result.empty


def test_a_genuinely_shared_mobile_is_still_flagged() -> None:
    cfg = get_config()
    df = pd.DataFrame({
        "BeneficiaryID": [f"BEN_{i}" for i in range(5)],
        "MobileNumber": ["9876543210"] * 5,
    })
    result = CloneDetectionRule().evaluate({"beneficiaries": df}, cfg)
    assert set(result["record_id"]) == {f"BEN_{i}" for i in range(5)}
