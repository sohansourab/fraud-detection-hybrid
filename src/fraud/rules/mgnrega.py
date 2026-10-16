"""Domain 2 rules: MGNREGA (labor fraud).

Selection is vectorized with boolean masks / groupby; only rows that actually
match are iterated to build their evidence dicts.
"""
from __future__ import annotations

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
        days_worked = df["DaysWorked"].fillna(0)
        mask = (days_worked > max_days).astype(bool)
        matched = df[mask]
        rows = [
            (str(txn_id), {"days_worked": int(days), "max_allowed": max_days})
            for txn_id, days in zip(
                matched["TransactionID"], days_worked[mask], strict=True
            )
        ]
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
        work_code = df["WorkCode"].astype(str)
        mask = work_code.str.endswith(suffix).astype(bool)
        matched = df[mask]
        rows = [
            (str(txn_id), {"work_code": str(code)})
            for txn_id, code in zip(
                matched["TransactionID"], work_code[mask], strict=True
            )
        ]
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
        days_worked = df["DaysWorked"].fillna(0)
        wage_rate = df["WageRate"].fillna(0)
        total_amount = df["TotalAmount"].fillna(0)
        expected_amount = days_worked * wage_rate
        mask = ((total_amount != expected_amount) & (days_worked > 0)).astype(bool)
        matched = df[mask]
        rows = [
            (
                str(txn_id),
                {
                    "days_worked": int(days),
                    "wage_rate": int(wage),
                    "expected_amount": int(expected),
                    "actual_amount": int(total),
                    "discrepancy": int(total - expected),
                },
            )
            for txn_id, days, wage, expected, total in zip(
                matched["TransactionID"],
                days_worked[mask],
                wage_rate[mask],
                expected_amount[mask],
                total_amount[mask],
                strict=True,
            )
        ]
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
        days_worked = df["DaysWorked"].fillna(0)
        total_amount = df["TotalAmount"].fillna(0)
        mask = ((days_worked == 0) & (total_amount > 0)).astype(bool)
        matched = df[mask]
        rows = [
            (str(txn_id), {"days_worked": 0, "amount_paid": int(total)})
            for txn_id, total in zip(
                matched["TransactionID"], total_amount[mask], strict=True
            )
        ]
        return self._results(self.id, rows)


@register
class MusterRollCartelRule(Rule):
    """Rule 17: workers repeatedly appearing together in muster rolls.

    Co-occurrence counts are built with groupby/merge instead of per-row scans.
    When a transaction's job card has several qualifying co-workers, the most
    frequent one (ties broken by job card id) is reported, making output
    deterministic.
    """

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

        # Unique (muster roll, job card) pairs -> appearance counts per card.
        pairs = (
            df[["MusterRollID", "JobCardID"]]
            .dropna()
            .astype(str)
            .drop_duplicates()
        )
        appearances = pairs.groupby("JobCardID")["MusterRollID"].nunique()

        # Co-occurrence: self-join pairs within the same muster roll.
        merged = pairs.merge(pairs, on="MusterRollID", suffixes=("_x", "_y"))
        merged = merged[merged["JobCardID_x"] != merged["JobCardID_y"]]
        cooc = (
            merged.groupby(["JobCardID_x", "JobCardID_y"])
            .size()
            .rename("count")
            .reset_index()
        )
        cooc["appearances"] = cooc["JobCardID_x"].map(appearances)
        cooc["rate"] = cooc["count"] / cooc["appearances"]
        qualifying = cooc[
            (cooc["appearances"] > min_appearances) & (cooc["rate"] >= cartel_threshold)
        ].sort_values(["count", "JobCardID_y"], ascending=[False, True])
        best_member = qualifying.drop_duplicates("JobCardID_x").set_index("JobCardID_x")

        rows: list[tuple[str, dict[str, Any]]] = []
        if not best_member.empty:
            job_cards = df["JobCardID"].astype(str)
            mask = job_cards.isin(best_member.index).astype(bool)
            matched = df[mask]
            for txn_id, card in zip(
                matched["TransactionID"], job_cards[mask], strict=True
            ):
                info = best_member.loc[card]
                rows.append((
                    str(txn_id),
                    {
                        "job_card": card,
                        "cartel_member": info["JobCardID_y"],
                        "cooccurrence_rate": f"{info['rate']:.0%}",
                        "total_appearances": int(info["appearances"]),
                    },
                ))
        return self._results(self.id, rows)
