"""Regression test for Rule 025 (multi-scheme velocity).

Bug fixed in P1d: the rule matched beneficiary ids by substring against
record ids/names and could not see MGNREGA records at all (no JobCard ->
Beneficiary mapping). It now resolves records to beneficiaries with exact id
joins.
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
from fraud.rules.cross import MultiSchemeVelocityRule  # noqa: E402


def _tables() -> dict[str, pd.DataFrame]:
    beneficiaries = pd.DataFrame({
        "BeneficiaryID": ["BEN_1"],
        "JobCardID": ["JC_1"],
    })
    mgnrega = pd.DataFrame({
        "TransactionID": ["TXN_1"],
        "JobCardID": ["JC_1"],
        "MusterRollID": ["MR_1"],
    })
    pmjay = pd.DataFrame({"ClaimID": [], "BeneficiaryID": []})
    flagged = pd.DataFrame({
        "record_id": ["BEN_1", "TXN_1"],
        "domain": ["Civil Registry", "MGNREGA Labor"],
        "record_name": ["Alice", "JobCard: JC_1"],
    })
    return {
        "beneficiaries": beneficiaries,
        "mgnrega": mgnrega,
        "pmjay": pmjay,
        "flagged_records": flagged,
    }


def test_mgnrega_record_joins_to_beneficiary_and_is_flagged() -> None:
    """Before the fix only BEN_1 was seen (1 domain), so nothing was flagged."""
    result = MultiSchemeVelocityRule().evaluate(_tables(), get_config())
    assert set(result["record_id"]) == {"BEN_1", "TXN_1"}
