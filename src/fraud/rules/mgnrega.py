"""Domain 2 rules: MGNREGA (labor fraud).

Logic is copied verbatim from the original ``audit_scanner.py`` scanners;
optimizations/bug fixes are intentionally deferred to later steps.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from fraud.rules.base import Rule
from fraud.rules.registry import register


@register
class ImpossibleHumanRule(Rule):
    """Rule 5: more days worked in a muster roll cycle than is possible."""

    id = "RULE_005"
    domain = "MGNREGA Labor"
    name = "Impossible Human"
    pattern = "Overtime Fraud"
    description = "DaysWorked > 15 in a muster roll cycle - physically impossible"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["mgnrega"]
        max_days = cfg.mgnrega.max_days_per_cycle
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            days_worked = row["DaysWorked"] if pd.notna(row["DaysWorked"]) else 0
            if days_worked > max_days:
                rows.append((
                    str(row["TransactionID"]),
                    {"days_worked": int(days_worked), "max_allowed": max_days},
                ))
        return self._results(self.id, rows)


@register
class GhostProjectRule(Rule):
    """Rule 6: work code belonging to a non-existent project."""

    id = "RULE_006"
    domain = "MGNREGA Labor"
    name = "Ghost Project"
    pattern = "Fake Infrastructure"
    description = "WorkCode ends with _000 - non-existent project used to siphon funds"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["mgnrega"]
        suffix = cfg.mgnrega.ghost_project_suffix
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            work_code = str(row["WorkCode"])
            if work_code.endswith(suffix):
                rows.append((str(row["TransactionID"]), {"work_code": work_code}))
        return self._results(self.id, rows)


@register
class WageTheftRule(Rule):
    """Rule 7: paid amount does not equal days worked times wage rate."""

    id = "RULE_007"
    domain = "MGNREGA Labor"
    name = "Wage Theft"
    pattern = "Amount Mismatch"
    description = "TotalAmount != DaysWorked * WageRate - embezzlement detected"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["mgnrega"]
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            days_worked = row["DaysWorked"] if pd.notna(row["DaysWorked"]) else 0
            wage_rate = row["WageRate"] if pd.notna(row["WageRate"]) else 0
            total_amount = row["TotalAmount"] if pd.notna(row["TotalAmount"]) else 0
            expected_amount = days_worked * wage_rate
            if total_amount != expected_amount and days_worked > 0:
                rows.append((
                    str(row["TransactionID"]),
                    {
                        "days_worked": int(days_worked),
                        "wage_rate": int(wage_rate),
                        "expected_amount": int(expected_amount),
                        "actual_amount": int(total_amount),
                        "discrepancy": int(total_amount - expected_amount),
                    },
                ))
        return self._results(self.id, rows)


@register
class FreeMoneyRule(Rule):
    """Rule 8: payment made for zero days worked."""

    id = "RULE_008"
    domain = "MGNREGA Labor"
    name = "Free Money"
    pattern = "Zero Work Payment"
    description = "Payment made with zero days worked - direct theft"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["mgnrega"]
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            days_worked = row["DaysWorked"] if pd.notna(row["DaysWorked"]) else 0
            total_amount = row["TotalAmount"] if pd.notna(row["TotalAmount"]) else 0
            if days_worked == 0 and total_amount > 0:
                rows.append((
                    str(row["TransactionID"]),
                    {"days_worked": 0, "amount_paid": int(total_amount)},
                ))
        return self._results(self.id, rows)


@register
class MusterRollCartelRule(Rule):
    """Rule 17: workers repeatedly appearing together in muster rolls."""

    id = "RULE_017"
    domain = "MGNREGA Labor"
    name = "Muster Roll Cartel"
    pattern = "Worker Collusion Network"
    description = "Same JobCardIDs appearing together in >80% of muster rolls - contractor cartel"
    severity = 35

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["mgnrega"]
        min_appearances = cfg.mgnrega.min_cartel_appearances
        cartel_threshold = cfg.mgnrega.cartel_threshold

        muster_roll_workers: dict[str, set] = {}
        for muster_id, group in df.groupby("MusterRollID"):
            workers = set(group["JobCardID"].dropna().astype(str))
            muster_roll_workers[str(muster_id)] = workers

        job_card_cooccurrence: dict[str, Counter] = {}
        for _, workers in muster_roll_workers.items():
            for worker in workers:
                if worker not in job_card_cooccurrence:
                    job_card_cooccurrence[worker] = Counter()
                for other in workers:
                    if other != worker:
                        job_card_cooccurrence[worker][other] += 1

        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            job_card_id = str(row["JobCardID"])
            if job_card_id in job_card_cooccurrence:
                total_appearances = sum(
                    1 for workers in muster_roll_workers.values() if job_card_id in workers
                )
                if total_appearances > min_appearances:
                    for other_card, cooccur_count in job_card_cooccurrence[job_card_id].items():
                        cooccurrence_rate = cooccur_count / total_appearances
                        if cooccurrence_rate >= cartel_threshold:
                            rows.append((
                                str(row["TransactionID"]),
                                {
                                    "job_card": job_card_id,
                                    "cartel_member": other_card,
                                    "cooccurrence_rate": f"{cooccurrence_rate:.0%}",
                                    "total_appearances": total_appearances,
                                },
                            ))
                            break  # Only flag once per transaction
        return self._results(self.id, rows)
