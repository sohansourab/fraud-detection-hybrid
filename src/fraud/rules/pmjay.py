"""Domain 3 rules: PM-JAY (medical fraud).

Logic is copied verbatim from the original ``audit_scanner.py`` scanners;
optimizations/bug fixes are intentionally deferred to later steps.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from fraud.rules.base import Rule
from fraud.rules.registry import register


@register
class TimeTravelRule(Rule):
    """Rule 9: discharge date before admission date."""

    id = "RULE_009"
    domain = "PM-JAY Medical"
    name = "Time Travel"
    pattern = "Impossible Dates"
    description = "DischargeDate before AdmissionDate - fake/backdated claim"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["pmjay"]
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            admission_date = row["AdmissionDate"]
            discharge_date = row["DischargeDate"]
            if pd.notna(admission_date) and pd.notna(discharge_date):
                if discharge_date < admission_date:
                    rows.append((
                        str(row["ClaimID"]),
                        {
                            "admission_date": str(admission_date.date()),
                            "discharge_date": str(discharge_date.date()),
                        },
                    ))
        return self._results(self.id, rows)


@register
class BiologicalMismatchRule(Rule):
    """Rule 10: male patient claiming a female-only procedure."""

    id = "RULE_010"
    domain = "PM-JAY Medical"
    name = "Biological Mismatch"
    pattern = "Gender Procedure Fraud"
    description = "Male patient claiming Hysterectomy - impossible procedure"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["pmjay"]
        beneficiaries = tables["beneficiaries"]
        female_only = cfg.pmjay.female_only_procedures
        gender_map = dict(zip(beneficiaries["BeneficiaryID"], beneficiaries["Gender"]))
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            ben_id = str(row["BeneficiaryID"])
            procedure = str(row["ProcedureName"])
            gender = gender_map.get(ben_id, "Unknown")
            if gender == "M" and procedure in female_only:
                rows.append((
                    str(row["ClaimID"]),
                    {"gender": "Male", "procedure": procedure},
                ))
        return self._results(self.id, rows)


@register
class MassiveUpcodingRule(Rule):
    """Rule 11: general ward/consultation billed above the allowed cost."""

    id = "RULE_011"
    domain = "PM-JAY Medical"
    name = "Massive Upcoding"
    pattern = "Billing Fraud"
    description = "General Ward/Consultation costing > Rs.50,000 - inflated billing"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["pmjay"]
        general_procedures = cfg.pmjay.general_procedures
        max_cost = cfg.pmjay.max_general_ward_cost
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            procedure = str(row["ProcedureName"])
            claim_amount = row["ClaimAmount"] if pd.notna(row["ClaimAmount"]) else 0
            if procedure in general_procedures and claim_amount > max_cost:
                rows.append((
                    str(row["ClaimID"]),
                    {
                        "procedure": procedure,
                        "claim_amount": int(claim_amount),
                        "threshold": max_cost,
                    },
                ))
        return self._results(self.id, rows)


@register
class BlacklistedHospitalRule(Rule):
    """Rule 12: claim filed by a blacklisted hospital."""

    id = "RULE_012"
    domain = "PM-JAY Medical"
    name = "Blacklisted Hospital"
    pattern = "Banned Entity"
    description = "Claim from blacklisted hospital HOSP_999"
    severity = 25

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        df = tables["pmjay"]
        blacklisted = cfg.pmjay.blacklisted_hospital
        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            hospital_id = str(row["HospitalID"])
            if hospital_id == blacklisted:
                rows.append((str(row["ClaimID"]), {"hospital_id": hospital_id}))
        return self._results(self.id, rows)


@register
class ProcedureMillRule(Rule):
    """Rule 21: hospital performing the same procedure excessively.

    NOTE: preserved verbatim. The original scanner computed per-hospital /
    procedure / month counts but never emitted a flag from them, so this rule
    currently flags nothing. The missing detection is fixed in a later step.
    """

    id = "RULE_021"
    domain = "PM-JAY Medical"
    name = "Procedure Mill"
    pattern = "Excessive Procedure Volume"
    description = "Hospital performs same high-value procedure >50 times/month - unnecessary surgeries"
    severity = 35

    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        # Original behaviour: no flags emitted (threshold was never applied).
        return self._results(self.id, [])
