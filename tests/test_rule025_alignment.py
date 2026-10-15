"""Regression test for the Rule 025 JobCardID -> BeneficiaryID map.

Bug fixed in P1e: the P1d code built the map with

    dict(zip(beneficiaries["JobCardID"].dropna().astype(str),
             beneficiaries["BeneficiaryID"].astype(str)))

``dropna()`` shortens the key column but not the value column, so ``zip``
pairs them by position and every row after the first NaN gets the wrong
beneficiary. The map must be built from the *same* filtered frame.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.rules.cross import MultiSchemeVelocityRule  # noqa: E402


def _job_card_map(job_cards: list) -> dict[str, str]:
    beneficiaries = pd.DataFrame({
        "BeneficiaryID": [f"BEN_{i}" for i in range(len(job_cards))],
        "JobCardID": job_cards,
    })
    lookup = MultiSchemeVelocityRule._beneficiary_lookup(
        {"beneficiaries": beneficiaries}
    )
    return lookup["job_card_to_ben"]


def test_job_card_map_aligned_when_nan_is_first_row() -> None:
    """NaN in row 0 must not shift JC_1 onto BEN_0."""
    result = _job_card_map([None, "JC_1", "JC_2"])
    assert result == {"JC_1": "BEN_1", "JC_2": "BEN_2"}


def test_job_card_map_aligned_when_nan_is_middle_row() -> None:
    """Rows after an interior NaN must keep their own beneficiary."""
    result = _job_card_map(["JC_0", None, "JC_2", "JC_3"])
    assert result == {"JC_0": "BEN_0", "JC_2": "BEN_2", "JC_3": "BEN_3"}
