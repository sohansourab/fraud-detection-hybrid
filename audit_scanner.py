#!/usr/bin/env python3
"""
Multi-Domain Fraud Scanner - thin runner over the rule registry.

All detection logic lives in ``src/fraud/rules`` (one class per rule). This
module only:
  1. loads the input tables,
  2. runs every registered rule,
  3. merges per-rule flags into per-record reports,
  4. prints and exports the summary.

Domains: Civil Registry (identity), MGNREGA (labor), PM-JAY (medical) and the
cross-domain multi-scheme rule.
"""

import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Make the ``src`` package importable when run as a legacy root-level script.
_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from fraud.config import get_config  # noqa: E402
from fraud.rules import get_rules  # noqa: E402

_CONFIG = get_config()

# Domain ordering + the table each domain is scanned on.
DOMAIN_ORDER = ["Civil Registry", "MGNREGA Labor", "PM-JAY Medical"]
DOMAIN_TABLES = {
    "Civil Registry": "beneficiaries",
    "MGNREGA Labor": "mgnrega",
    "PM-JAY Medical": "pmjay",
}
ID_COLUMNS = {
    "Civil Registry": "BeneficiaryID",
    "MGNREGA Labor": "TransactionID",
    "PM-JAY Medical": "ClaimID",
}
CROSS_DOMAIN = "Cross-Domain"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class FraudReport:
    """Represents a fraud report for a single record."""
    record_id: str
    record_name: str
    domain: str
    flags: List[Dict[str, Any]]
    total_risk_score: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_name": self.record_name,
            "domain": self.domain,
            "flags": self.flags,
            "total_risk_score": self.total_risk_score
        }


# =============================================================================
# DATA LOADING
# =============================================================================

def load_tables() -> Dict[str, pd.DataFrame]:
    """Load the three input tables exactly as the legacy scanners did."""
    beneficiaries = pd.read_csv(_CONFIG.paths.beneficiaries, dtype={
        'BeneficiaryID': str,
        'Name': str,
        'Age': 'Int64',
        'Gender': str,
        'MobileNumber': str,
        'JobCardID': str,
        'FamilyID': str
    })
    beneficiaries['MobileNumber'] = (
        beneficiaries['MobileNumber']
        .astype(str)
        .str.replace(r'\D', '', regex=True)
        .str.strip()
    )
    logger.info(f"[Civil Registry] Loaded {len(beneficiaries)} records")

    mgnrega = pd.read_csv(_CONFIG.paths.mgnrega, dtype={
        'TransactionID': str,
        'JobCardID': str,
        'WorkCode': str,
        'MusterRollID': str,
        'DaysWorked': 'Int64',
        'WageRate': 'Int64',
        'TotalAmount': 'Int64'
    })
    logger.info(f"[MGNREGA] Loaded {len(mgnrega)} transactions")

    pmjay = pd.read_csv(_CONFIG.paths.pmjay, dtype={
        'ClaimID': str,
        'BeneficiaryID': str,
        'HospitalID': str,
        'ProcedureName': str,
        'ClaimAmount': 'Int64',
        'PatientStatus': str
    }, parse_dates=['AdmissionDate', 'DischargeDate'])
    logger.info(f"[PM-JAY] Loaded {len(pmjay)} claims")

    return {
        "beneficiaries": beneficiaries,
        "mgnrega": mgnrega,
        "pmjay": pmjay,
    }


# =============================================================================
# RULE EXECUTION
# =============================================================================

def _record_id(domain: str, row: pd.Series) -> str:
    return str(row[ID_COLUMNS[domain]])


def _record_name(domain: str, row: pd.Series) -> str:
    if domain == "Civil Registry":
        return str(row["Name"])
    if domain == "MGNREGA Labor":
        return f"JobCard: {str(row['JobCardID'])}"
    return f"Beneficiary: {str(row['BeneficiaryID'])} | Hospital: {str(row['HospitalID'])}"


def _run_domain_rules(tables: Dict[str, pd.DataFrame], rules: List[Any]) -> Dict[str, List[Any]]:
    """Evaluate rules and group ``(rule, evidence)`` pairs by record id."""
    flags_by_record: Dict[str, List[Any]] = {}
    for rule in rules:
        result = rule.evaluate(tables, _CONFIG)
        for record_id, evidence_json in zip(result["record_id"], result["evidence_json"]):
            flags_by_record.setdefault(str(record_id), []).append(
                (rule, json.loads(evidence_json))
            )
    return flags_by_record


def _build_reports(
    domain: str, df: pd.DataFrame, flags_by_record: Dict[str, List[Any]]
) -> List[FraudReport]:
    """Turn grouped flags into per-record reports, preserving row order."""
    reports: List[FraudReport] = []
    for _, row in df.iterrows():
        entries = flags_by_record.get(_record_id(domain, row))
        if not entries:
            continue
        flags = [rule.flag(evidence) for rule, evidence in entries]
        reports.append(FraudReport(
            record_id=_record_id(domain, row),
            record_name=_record_name(domain, row),
            domain=domain,
            flags=flags,
            total_risk_score=sum(flag['risk_score'] for flag in flags),
        ))
    return reports


# =============================================================================
# MASTER SCANNER - ORCHESTRATOR
# =============================================================================

class MasterFraudScanner:
    """Master Fraud Scanner - runs the rule registry and aggregates results."""

    OUTPUT_PATH = _CONFIG.paths.output

    def __init__(self):
        self.all_reports: List[FraudReport] = []
        self.domain_summaries: Dict[str, Dict] = {}

    def run_all_scans(self) -> None:
        """Execute all registered rules."""
        print("\n" + "="*70)
        print("  MULTI-DOMAIN FRAUD DETECTION SYSTEM")
        print(f"  {len(get_rules())} Rules | 3 Domains + Cross-Domain | O(N) Linear Scan")
        print("="*70 + "\n")

        tables = load_tables()
        rules = get_rules()
        self.all_reports = []
        self.domain_summaries = {}

        for index, domain in enumerate(DOMAIN_ORDER, start=1):
            print(f"[{index}/3] Scanning {domain}...")
            df = tables[DOMAIN_TABLES[domain]]
            domain_rules = [rule for rule in rules if rule.domain == domain]
            flags_by_record = _run_domain_rules(tables, domain_rules)
            reports = _build_reports(domain, df, flags_by_record)
            self.all_reports.extend(reports)
            self.domain_summaries[domain] = {
                "records_scanned": len(df),
                "flagged": len(reports),
                "rules": [rule.id for rule in domain_rules],
            }

        print("[4/4] Running Cross-Domain Analysis (Multi-Scheme Velocity)...")
        self._run_cross_domain(tables, rules)

    def _run_cross_domain(self, tables: Dict[str, pd.DataFrame], rules: List[Any]) -> None:
        """Run cross-domain rules against the currently flagged records."""
        cross_rules = [rule for rule in rules if rule.domain == CROSS_DOMAIN]
        if not cross_rules:
            return

        tables["flagged_records"] = pd.DataFrame(
            [
                {"record_id": r.record_id, "domain": r.domain, "record_name": r.record_name}
                for r in self.all_reports
            ],
            columns=["record_id", "domain", "record_name"],
        )
        by_id = {report.record_id: report for report in self.all_reports}

        for rule in cross_rules:
            result = rule.evaluate(tables, _CONFIG)
            for record_id, evidence_json in zip(result["record_id"], result["evidence_json"]):
                report = by_id.get(str(record_id))
                if report is None:
                    continue
                if any(flag['rule_id'] == rule.id for flag in report.flags):
                    continue
                report.flags.append(rule.flag(json.loads(evidence_json)))
                report.total_risk_score += rule.severity

    def get_master_summary(self) -> Dict[str, Any]:
        """Generate master summary across all domains."""
        total_scanned = sum(d.get("records_scanned", 0) for d in self.domain_summaries.values())
        total_flagged = len(self.all_reports)

        # Rule breakdown across all domains
        rule_counts = Counter()
        for report in self.all_reports:
            for flag in report.flags:
                rule_counts[flag['rule_id']] += 1

        # Risk distribution
        risk_distribution = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for report in self.all_reports:
            if report.total_risk_score <= _CONFIG.risk_bands.low_max:
                risk_distribution["low"] += 1
            elif report.total_risk_score <= _CONFIG.risk_bands.medium_max:
                risk_distribution["medium"] += 1
            elif report.total_risk_score <= _CONFIG.risk_bands.high_max:
                risk_distribution["high"] += 1
            else:
                risk_distribution["critical"] += 1

        # All rules from the registry
        all_rules = {rule.id: rule for rule in get_rules()}

        return {
            "total_records_scanned": total_scanned,
            "total_flagged": total_flagged,
            "flag_rate": f"{(total_flagged / total_scanned * 100):.2f}%" if total_scanned > 0 else "0%",
            "domain_breakdown": self.domain_summaries,
            "rule_breakdown": {
                rule_id: {
                    "name": all_rules[rule_id].name,
                    "count": count
                }
                for rule_id, count in sorted(rule_counts.items())
            },
            "risk_distribution": risk_distribution
        }

    def export_json(self) -> None:
        """Export all fraud reports to JSON."""
        Path(self.OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)

        output = {
            "scan_metadata": {
                "scan_timestamp": datetime.now().isoformat(),
                "domains_scanned": list(self.domain_summaries.keys()),
                "total_rules": len(get_rules()),
                "rules_applied": [
                    rule.id for rule in get_rules() if rule.domain != CROSS_DOMAIN
                ]
            },
            "summary": self.get_master_summary(),
            "flagged_records": [r.to_dict() for r in self.all_reports]
        }

        with open(self.OUTPUT_PATH, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"Exported master report to {self.OUTPUT_PATH}")

    def print_report(self) -> None:
        """Print formatted report to console."""
        summary = self.get_master_summary()

        print("\n" + "="*70)
        print("  FRAUD DETECTION REPORT")
        print("="*70)

        print(f"\n[OVERVIEW]")
        print(f"  Total Records Scanned: {summary['total_records_scanned']:,}")
        print(f"  Total Flagged: {summary['total_flagged']:,} ({summary['flag_rate']})")

        print(f"\n[DOMAIN BREAKDOWN]")
        for domain, data in summary['domain_breakdown'].items():
            flag_rate = (data['flagged'] / data['records_scanned'] * 100) if data['records_scanned'] > 0 else 0
            print(f"  * {domain}: {data['flagged']:,} / {data['records_scanned']:,} ({flag_rate:.2f}%)")

        print(f"\n[RULE BREAKDOWN]")
        for rule_id, data in summary['rule_breakdown'].items():
            print(f"  * {rule_id}: {data['name']} - {data['count']:,} flags")

        print(f"\n[RISK DISTRIBUTION]")
        for level, count in summary['risk_distribution'].items():
            print(f"  * {level.upper()}: {count:,}")

        print("\n" + "="*70)

        # Top 10 highest risk cases
        if self.all_reports:
            print("\n[TOP 10 HIGHEST RISK CASES]")
            sorted_reports = sorted(self.all_reports, key=lambda x: x.total_risk_score, reverse=True)[:10]
            for i, report in enumerate(sorted_reports, 1):
                print(f"\n  {i}. [{report.domain}] {report.record_id}")
                print(f"     {report.record_name}")
                print(f"     Risk Score: {report.total_risk_score}")
                print(f"     Flags: {[f['rule_id'] for f in report.flags]}")

        print("\n" + "="*70)


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    """Main execution function."""
    scanner = MasterFraudScanner()

    # Run all domain scans
    scanner.run_all_scans()

    # Print report to console
    scanner.print_report()

    # Export to JSON
    scanner.export_json()

    print(f"\n[SUCCESS] Report exported to: {scanner.OUTPUT_PATH}")


if __name__ == "__main__":
    main()
