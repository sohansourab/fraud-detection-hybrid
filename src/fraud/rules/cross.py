"""Cross-domain rules.

Rule 25 operates on records already flagged by the per-domain rules; the
runner exposes them to ``evaluate`` via ``tables["flagged_records"]`` (a frame
with ``record_id``, ``domain`` and ``record_name`` columns). The other tables
(``beneficiaries``, ``mgnrega``, ``pmjay``) are used to resolve a flagged
record to its exact ``BeneficiaryID``.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from fraud.rules.base import Rule
from fraud.rules.registry import register

CIVIL = "Civil Registry"
MGNREGA = "MGNREGA Labor"
PMJAY = "PM-JAY Medical"


@register
class MultiSchemeVelocityRule(Rule):
    """Rule 25: same beneficiary flagged in multiple schemes.

    Record -> beneficiary resolution is done with exact id lookups (no
    substring matching). The result depends only on the *set* of flagged
    records, not on the order of ``tables["flagged_records"]``: membership is
    resolved per record and the reported ``flagged_domains`` are sorted.
    """

    id = "RULE_025"
    domain = "Cross-Domain"
    name = "Multi-Scheme Velocity"
    pattern = "Cross-Domain Fraud"
    description = "Same beneficiary flagged in multiple schemes - professional fraudster"
    severity = 40

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        flagged = tables.get("flagged_records")
        if flagged is None or flagged.empty:
            return self._results(self.id, [])

        min_domains = cfg.cross_domain.min_domains
        prefix = cfg.cross_domain.beneficiary_prefix
        lookup = self._beneficiary_lookup(tables)

        beneficiary_domains: dict[str, set] = {}
        beneficiary_records: dict[str, list[str]] = {}
        for record_id, domain in zip(
            flagged["record_id"].astype(str), flagged["domain"].astype(str)
        ):
            ben_id = self._beneficiary_of(record_id, domain, lookup)
            if ben_id and ben_id.startswith(prefix):
                beneficiary_domains.setdefault(ben_id, set()).add(domain)
                beneficiary_records.setdefault(ben_id, []).append(record_id)

        rows: list[tuple[str, dict[str, Any]]] = []
        already_flagged: set[str] = set()
        for ben_id, domains in beneficiary_domains.items():
            if len(domains) < min_domains:
                continue
            for record_id in beneficiary_records[ben_id]:
                if record_id in already_flagged:
                    continue
                already_flagged.add(record_id)
                rows.append((
                    record_id,
                    {
                        "beneficiary_id": ben_id,
                        "flagged_domains": sorted(domains),
                        "domain_count": len(domains),
                    },
                ))
        return self._results(self.id, rows)

    @staticmethod
    def _beneficiary_lookup(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, str]]:
        """Exact id maps: job card -> beneficiary, txn -> job card, claim -> beneficiary."""
        beneficiaries = tables.get("beneficiaries")
        mgnrega = tables.get("mgnrega")
        pmjay = tables.get("pmjay")
        lookup: dict[str, dict[str, str]] = {
            "job_card_to_ben": {},
            "txn_to_job_card": {},
            "claim_to_ben": {},
        }
        if beneficiaries is not None:
            # Build from the *same* filtered frame: filtering one column with
            # dropna() and zipping it against the unfiltered other column
            # pairs rows by position and misaligns everything after the first
            # NaN (fixed in P1e).
            sub = beneficiaries[["JobCardID", "BeneficiaryID"]].dropna(
                subset=["JobCardID"]
            )
            lookup["job_card_to_ben"] = dict(zip(
                sub["JobCardID"].astype(str),
                sub["BeneficiaryID"].astype(str),
            ))
        if mgnrega is not None:
            lookup["txn_to_job_card"] = dict(zip(
                mgnrega["TransactionID"].astype(str),
                mgnrega["JobCardID"].astype(str),
            ))
        if pmjay is not None:
            lookup["claim_to_ben"] = dict(zip(
                pmjay["ClaimID"].astype(str),
                pmjay["BeneficiaryID"].astype(str),
            ))
        return lookup

    @staticmethod
    def _beneficiary_of(
        record_id: str, domain: str, lookup: dict[str, dict[str, str]]
    ) -> str | None:
        if domain == CIVIL:
            return record_id
        if domain == MGNREGA:
            job_card = lookup["txn_to_job_card"].get(record_id)
            return lookup["job_card_to_ben"].get(job_card) if job_card else None
        if domain == PMJAY:
            return lookup["claim_to_ben"].get(record_id)
        return None
