"""Domain 3 rules: PM-JAY (medical fraud).

Selection is vectorized with boolean masks / map; only rows that actually
match are iterated to build their evidence dicts.
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
        admission = df["AdmissionDate"]
        discharge = df["DischargeDate"]
        mask = (
            admission.notna()
            & discharge.notna()
            & (discharge < admission).fillna(False)
        ).fillna(False).astype(bool)
        matched = df[mask]
        rows = [
            (
                str(claim_id),
                {
                    "admission_date": str(adm.date()),
                    "discharge_date": str(dis.date()),
                },
            )
            for claim_id, adm, dis in zip(
                matched["ClaimID"],
                matched["AdmissionDate"],
                matched["DischargeDate"],
                strict=True,
            )
        ]
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
        gender_map = dict(zip(
            beneficiaries["BeneficiaryID"],
            beneficiaries["Gender"],
            strict=True,
        ))
        procedure = df["ProcedureName"].astype(str)
        gender = df["BeneficiaryID"].astype(str).map(gender_map)
        mask = ((gender == "M") & procedure.isin(female_only)).astype(bool)
        matched = df[mask]
        rows = [
            (str(claim_id), {"gender": "Male", "procedure": str(proc)})
            for claim_id, proc in zip(
                matched["ClaimID"], procedure[mask], strict=True
            )
        ]
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
        procedure = df["ProcedureName"].astype(str)
        claim_amount = df["ClaimAmount"].fillna(0)
        mask = (procedure.isin(general_procedures) & (claim_amount > max_cost)).astype(bool)
        matched = df[mask]
        rows = [
            (
                str(claim_id),
                {
                    "procedure": str(proc),
                    "claim_amount": int(amount),
                    "threshold": max_cost,
                },
            )
            for claim_id, proc, amount in zip(
                matched["ClaimID"], procedure[mask], claim_amount[mask], strict=True
            )
        ]
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
        hospital_id = df["HospitalID"].astype(str)
        mask = (hospital_id == blacklisted).astype(bool)
        matched = df[mask]
        rows = [
            (str(claim_id), {"hospital_id": str(hospital)})
            for claim_id, hospital in zip(
                matched["ClaimID"], hospital_id[mask], strict=True
            )
        ]
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
        df = tables["pmjay"]
        threshold = cfg.pmjay.procedure_mill_threshold
        if df.empty:
            return self._results(self.id, [])

        # Build the (hospital, procedure, month) keys in a derived frame so the
        # input table is never mutated.
        keys = pd.DataFrame({
            "HospitalID": df["HospitalID"].astype(str),
            "ProcedureName": df["ProcedureName"].astype(str),
            "month": pd.to_datetime(df["AdmissionDate"]).dt.to_period("M").astype(str),
        })
        counts = (
            keys.groupby(["HospitalID", "ProcedureName", "month"])
            .size()
            .rename("procedure_count")
            .reset_index()
        )
        merged = keys.merge(
            counts, on=["HospitalID", "ProcedureName", "month"], how="left"
        )
        mask = (merged["procedure_count"] > threshold).to_numpy()
        matched = df[mask]
        flagged = merged[mask]
        rows = [
            (
                str(claim_id),
                {
                    "hospital_id": hospital,
                    "procedure": procedure,
                    "month": month,
                    "procedure_count": int(count),
                    "threshold": threshold,
                },
            )
            for claim_id, hospital, procedure, month, count in zip(
                matched["ClaimID"],
                flagged["HospitalID"],
                flagged["ProcedureName"],
                flagged["month"],
                flagged["procedure_count"],
                strict=True,
            )
        ]
        return self._results(self.id, rows)
