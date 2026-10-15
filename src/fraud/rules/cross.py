"""Cross-domain rules.

Rule 25 operates on records already flagged by the per-domain rules; the
runner exposes them to ``evaluate`` via ``tables["flagged_records"]`` (a frame
with ``record_id``, ``domain`` and ``record_name`` columns).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from fraud.rules.base import Rule
from fraud.rules.registry import register


@register
class MultiSchemeVelocityRule(Rule):
    """Rule 25: same beneficiary flagged in multiple schemes."""

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

        # Collect the set of domains each beneficiary was flagged in.
        beneficiary_domains: dict[str, set] = {}
        for row in flagged.itertuples(index=False):
            ben_id = None
            if row.domain == "Civil Registry":
                ben_id = row.record_id
            elif row.domain == "MGNREGA Labor":
                # No direct JobCard -> BeneficiaryID mapping (kept as before).
                if "JobCard:" in row.record_name:
                    pass
            elif row.domain == "PM-JAY Medical":
                if "Beneficiary:" in row.record_name:
                    ben_id = row.record_name.split("|")[0].replace("Beneficiary:", "").strip()

            if ben_id and ben_id.startswith(prefix):
                beneficiary_domains.setdefault(ben_id, set()).add(row.domain)

        rows: list[tuple[str, dict[str, Any]]] = []
        already_flagged: set[str] = set()
        for ben_id, domains in beneficiary_domains.items():
            if len(domains) < min_domains:
                continue
            for row in flagged.itertuples(index=False):
                if ben_id in row.record_id or ben_id in row.record_name:
                    if row.record_id in already_flagged:
                        continue
                    already_flagged.add(row.record_id)
                    rows.append((
                        row.record_id,
                        {
                            "beneficiary_id": ben_id,
                            "flagged_domains": list(domains),
                            "domain_count": len(domains),
                        },
                    ))
        return self._results(self.id, rows)
