"""Domain 1 rules: Civil Registry (identity fraud).

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
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            mobile = str(row["MobileNumber"])
            if mobile == dummy_mobile:
                rows.append((str(row["BeneficiaryID"]), {"mobile_number": mobile}))
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
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            age = row["Age"]
            job_card_id = row["JobCardID"]
            if pd.notna(age) and age < min_adult_age:
                if pd.notna(job_card_id) and str(job_card_id).strip():
                    rows.append((
                        str(row["BeneficiaryID"]),
                        {"age": int(age), "job_card_id": str(job_card_id)},
                    ))
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
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            age = row["Age"]
            if pd.notna(age) and age > max_normal_age:
                rows.append((str(row["BeneficiaryID"]), {"age": int(age)}))
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
        family_counts = Counter(df["FamilyID"].dropna().astype(str))
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            family_id = row["FamilyID"]
            if pd.notna(family_id):
                family_size = family_counts.get(str(family_id), 0)
                if family_size > max_family_size:
                    rows.append((
                        str(row["BeneficiaryID"]),
                        {"family_id": str(family_id), "family_size": family_size},
                    ))
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
        valid_mobiles = df[df["MobileNumber"] != dummy_mobile]["MobileNumber"].dropna().astype(str)
        mobile_counts = Counter(valid_mobiles)
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            mobile = str(row["MobileNumber"])
            if mobile != dummy_mobile:
                mobile_share_count = mobile_counts.get(mobile, 0)
                if mobile_share_count > max_mobile_sharing:
                    rows.append((
                        str(row["BeneficiaryID"]),
                        {"mobile_number": mobile, "shared_by": mobile_share_count},
                    ))
        return self._results(self.id, rows)
