"""Domain 1 rules: Civil Registry (identity fraud).

Selection is vectorized with boolean masks; only rows that actually match are
iterated to build their evidence dicts.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from fraud.rules.base import Rule
from fraud.rules.registry import register


@register
class InvalidMobileRule(Rule):
    """Rule 1: mobile number is the dummy value 9999999999."""

    id = "RULE_001"
    domain = "Civil Registry"
    name = "Invalid Mobile Number"
    pattern = "Mob of 999"
    description = "Mobile number is dummy value (9999999999) - potential data manipulation"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["beneficiaries"]
        dummy_mobile = cfg.civil_registry.dummy_mobile
        matched = df[df["MobileNumber"] == dummy_mobile]
        rows = [
            (str(ben_id), {"mobile_number": str(mobile)})
            for ben_id, mobile in zip(
                matched["BeneficiaryID"], matched["MobileNumber"], strict=True
            )
        ]
        return self._results(self.id, rows)


@register
class UnderageWithJobCardRule(Rule):
    """Rule 2: a minor (<18) holds a MGNREGA job card."""

    id = "RULE_002"
    domain = "Civil Registry"
    name = "Underage with Job Card"
    pattern = "Child Labor"
    description = "Minor (<18) has Job Card - MGNREGA violation"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["beneficiaries"]
        min_adult_age = cfg.civil_registry.min_adult_age
        age = df["Age"]
        job_card = df["JobCardID"]
        mask = (
            age.notna()
            & (age < min_adult_age).fillna(False)
            & job_card.notna()
            & (job_card.astype(str).str.strip() != "")
        ).fillna(False).astype(bool)
        matched = df[mask]
        rows = [
            (str(ben_id), {"age": int(row_age), "job_card_id": str(job_card_id)})
            for ben_id, row_age, job_card_id in zip(
                matched["BeneficiaryID"], matched["Age"], matched["JobCardID"], strict=True
            )
        ]
        return self._results(self.id, rows)


@register
class SuspiciousAgeRule(Rule):
    """Rule 3: implausibly old beneficiary (>100)."""

    id = "RULE_003"
    domain = "Civil Registry"
    name = "Suspicious Age"
    pattern = "Centenarian Ghost"
    description = "Age >100 years - potential ghost beneficiary"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["beneficiaries"]
        max_normal_age = cfg.civil_registry.max_normal_age
        age = df["Age"]
        mask = (age.notna() & (age > max_normal_age).fillna(False)).fillna(False).astype(bool)
        matched = df[mask]
        rows = [
            (str(ben_id), {"age": int(row_age)})
            for ben_id, row_age in zip(
                matched["BeneficiaryID"], matched["Age"], strict=True
            )
        ]
        return self._results(self.id, rows)


@register
class MegaFamilyRule(Rule):
    """Rule 4: family with more than the allowed number of members."""

    id = "RULE_004"
    domain = "Civil Registry"
    name = "Mega Family"
    pattern = "Ration Hoarding"
    description = "Family has >15 members - potential ration hoarding"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["beneficiaries"]
        max_family_size = cfg.civil_registry.max_family_size
        family = df["FamilyID"]
        family_sizes = family.dropna().astype(str).value_counts()
        size_per_row = family.astype(str).map(family_sizes).fillna(0)
        mask = (
            family.notna() & (size_per_row > max_family_size)
        ).fillna(False).astype(bool)
        matched = df[mask]
        rows = [
            (str(ben_id), {"family_id": str(family_id), "family_size": int(size)})
            for ben_id, family_id, size in zip(
                matched["BeneficiaryID"], matched["FamilyID"], size_per_row[mask], strict=True
            )
        ]
        return self._results(self.id, rows)


@register
class CloneDetectionRule(Rule):
    """Rule 13: a mobile number shared by more than the allowed people."""

    id = "RULE_013"
    domain = "Civil Registry"
    name = "Clone Detection"
    pattern = "Mobile Sharing Ring"
    description = "Mobile number shared by >3 beneficiaries - identity broker/farming"
    severity = 30

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["beneficiaries"]
        dummy_mobile = cfg.civil_registry.dummy_mobile
        max_mobile_sharing = cfg.civil_registry.max_mobile_sharing
        raw_mobile = df["MobileNumber"]
        mobile = raw_mobile.astype(str).str.strip()
        # A null/blank mobile is missing data, not a shared identity: it must
        # never be turned into "nan"/"" and then counted as a shared number.
        is_valid = (
            raw_mobile.notna()
            & mobile.ne("")
            & mobile.ne("nan")
            & mobile.ne("none")
            & mobile.ne(dummy_mobile)
        )
        share_counts = mobile[is_valid].value_counts()
        shared_by = mobile.map(share_counts).fillna(0)
        mask = (is_valid & (shared_by > max_mobile_sharing)).astype(bool)
        matched = df[mask]
        rows = [
            (str(ben_id), {"mobile_number": str(row_mobile), "shared_by": int(count)})
            for ben_id, row_mobile, count in zip(
                matched["BeneficiaryID"], mobile[mask], shared_by[mask], strict=True
            )
        ]
        return self._results(self.id, rows)
