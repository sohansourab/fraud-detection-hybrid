#!/usr/bin/env python3
"""
Civil Registry Fraud Scanner - Optimized Implementation
Detects identity fraud patterns in beneficiaries data using 4 deterministic rules.
"""

import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
from collections import Counter
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class FraudFlag:
    """Represents a single fraud detection flag."""
    rule_id: str
    rule_name: str
    description: str
    risk_score: int


@dataclass
class FraudReport:
    """Represents a fraud report for a single beneficiary."""
    beneficiary_id: str
    name: str
    flags: List[Dict[str, Any]]
    total_risk_score: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "beneficiary_id": self.beneficiary_id,
            "name": self.name,
            "flags": self.flags,
            "total_risk_score": self.total_risk_score
        }


class CivilRegistryFraudScanner:
    """
    Optimized fraud scanner for Civil Registry (Identity Fraud Detection).
    
    Implements 4 deterministic rules:
    1. Invalid Mobile Number (9999999999)
    2. Underage with Job Card (Age < 18 with JobCardID)
    3. Suspicious Age (>100 years)
    4. Mega Family (>15 members per FamilyID)
    """
    
    # Rule Configuration Constants
    RULES = {
        "RULE_001": {
            "name": "Invalid Mobile Number",
            "pattern": "Mob of 999",
            "risk_score": 25,
            "description": "Mobile number is dummy value (9999999999) - potential data manipulation"
        },
        "RULE_002": {
            "name": "Underage with Job Card",
            "pattern": "Child Labor",
            "risk_score": 25,
            "description": "Minor (<18) has Job Card - MGNREGA violation"
        },
        "RULE_003": {
            "name": "Suspicious Age",
            "pattern": "Centenarian Ghost",
            "risk_score": 25,
            "description": "Age >100 years - potential ghost beneficiary"
        },
        "RULE_004": {
            "name": "Mega Family",
            "pattern": "Ration Hoarding",
            "risk_score": 25,
            "description": "Family has >15 members - potential ration hoarding"
        }
    }
    
    # Thresholds
    DUMMY_MOBILE = "9999999999"
    MIN_ADULT_AGE = 18
    MAX_NORMAL_AGE = 100
    MAX_FAMILY_SIZE = 15
    
    def __init__(self, data_path: str):
        """Initialize scanner with data path."""
        self.data_path = Path(data_path)
        self.df: pd.DataFrame = None
        self.family_counts: Dict[str, int] = {}
        self.fraud_reports: List[FraudReport] = []
        
    def load_data(self) -> bool:
        """Load and validate beneficiaries data."""
        try:
            self.df = pd.read_csv(self.data_path, dtype={
                'BeneficiaryID': str,
                'Name': str,
                'Age': 'Int64',  # Nullable integer
                'MobileNumber': str,
                'JobCardID': str,
                'FamilyID': str
            })
            
            # Normalize mobile numbers - remove non-digits and strip
            self.df['MobileNumber'] = (
                self.df['MobileNumber']
                .astype(str)
                .str.replace(r'\D', '', regex=True)  # Remove non-digits
                .str.strip()
            )
            
            logger.info(f"Loaded {len(self.df)} beneficiary records")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            return False
    
    def _precompute_family_sizes(self) -> None:
        """Pre-compute family sizes for O(1) lookup - Rule 4 optimization."""
        self.family_counts = Counter(
            self.df['FamilyID'].dropna().astype(str)
        )
        logger.info(f"Pre-computed sizes for {len(self.family_counts)} families")
    
    def _check_rule_001(self, mobile: str) -> bool:
        """Rule 1: Invalid Mobile Number (9999999999)."""
        return mobile == self.DUMMY_MOBILE
    
    def _check_rule_002(self, age: int, job_card_id: Any) -> bool:
        """Rule 2: Underage with Job Card."""
        if pd.isna(age):
            return False
        has_job_card = pd.notna(job_card_id) and str(job_card_id).strip() != ''
        return age < self.MIN_ADULT_AGE and has_job_card
    
    def _check_rule_003(self, age: int) -> bool:
        """Rule 3: Suspicious Age (>100)."""
        if pd.isna(age):
            return False
        return age > self.MAX_NORMAL_AGE
    
    def _check_rule_004(self, family_id: str) -> bool:
        """Rule 4: Mega Family (>15 members)."""
        if pd.isna(family_id):
            return False
        return self.family_counts.get(str(family_id), 0) > self.MAX_FAMILY_SIZE
    
    def scan(self) -> List[FraudReport]:
        """
        Execute O(N) linear scan applying all 4 rules.
        
        Returns:
            List of FraudReport objects for flagged beneficiaries.
        """
        if self.df is None:
            raise RuntimeError("Data not loaded. Call load_data() first.")
        
        # Pre-compute family sizes for Rule 4
        self._precompute_family_sizes()
        
        self.fraud_reports = []
        flagged_count = 0
        
        # Vectorized pre-filtering for potential optimization hints
        # (Still doing row-by-row for clear rule application)
        
        for _, row in self.df.iterrows():
            flags = []
            
            # Extract values once per row
            beneficiary_id = str(row['BeneficiaryID'])
            name = str(row['Name'])
            mobile = str(row['MobileNumber'])
            age = row['Age']
            job_card_id = row['JobCardID']
            family_id = row['FamilyID']
            
            # Rule 1: Invalid Mobile Number
            if self._check_rule_001(mobile):
                flags.append({
                    "rule_id": "RULE_001",
                    **self.RULES["RULE_001"],
                    "evidence": {"mobile_number": mobile}
                })
            
            # Rule 2: Underage with Job Card
            if self._check_rule_002(age, job_card_id):
                flags.append({
                    "rule_id": "RULE_002",
                    **self.RULES["RULE_002"],
                    "evidence": {
                        "age": int(age),
                        "job_card_id": str(job_card_id)
                    }
                })
            
            # Rule 3: Suspicious Age
            if self._check_rule_003(age):
                flags.append({
                    "rule_id": "RULE_003",
                    **self.RULES["RULE_003"],
                    "evidence": {"age": int(age)}
                })
            
            # Rule 4: Mega Family
            if self._check_rule_004(family_id):
                family_size = self.family_counts.get(str(family_id), 0)
                flags.append({
                    "rule_id": "RULE_004",
                    **self.RULES["RULE_004"],
                    "evidence": {
                        "family_id": str(family_id),
                        "family_size": family_size
                    }
                })
            
            # Only create report if at least one flag triggered
            if flags:
                total_risk = sum(f['risk_score'] for f in flags)
                report = FraudReport(
                    beneficiary_id=beneficiary_id,
                    name=name,
                    flags=flags,
                    total_risk_score=total_risk
                )
                self.fraud_reports.append(report)
                flagged_count += 1
        
        logger.info(f"Scan complete: {flagged_count} suspicious records out of {len(self.df)}")
        return self.fraud_reports
    
    def get_summary(self) -> Dict[str, Any]:
        """Generate summary statistics of the scan."""
        if not self.fraud_reports:
            return {"status": "no_flags", "total_records": len(self.df) if self.df is not None else 0}
        
        rule_counts = Counter()
        risk_distribution = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        
        for report in self.fraud_reports:
            for flag in report.flags:
                rule_counts[flag['rule_id']] += 1
            
            # Risk categorization
            if report.total_risk_score <= 25:
                risk_distribution["low"] += 1
            elif report.total_risk_score <= 50:
                risk_distribution["medium"] += 1
            elif report.total_risk_score <= 75:
                risk_distribution["high"] += 1
            else:
                risk_distribution["critical"] += 1
        
        return {
            "total_records_scanned": len(self.df),
            "total_flagged": len(self.fraud_reports),
            "flag_rate": f"{(len(self.fraud_reports) / len(self.df) * 100):.2f}%",
            "rule_breakdown": {
                rule_id: {
                    "name": self.RULES[rule_id]["name"],
                    "count": count
                }
                for rule_id, count in rule_counts.items()
            },
            "risk_distribution": risk_distribution
        }
    
    def export_json(self, output_path: str) -> None:
        """Export fraud reports to JSON file."""
        output = {
            "scan_metadata": {
                "source_file": str(self.data_path),
                "total_records": len(self.df),
                "rules_applied": list(self.RULES.keys())
            },
            "summary": self.get_summary(),
            "flagged_beneficiaries": [r.to_dict() for r in self.fraud_reports]
        }
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Exported report to {output_path}")


def main():
    """Main execution function."""
    # Initialize scanner
    scanner = CivilRegistryFraudScanner("data/beneficiaries.csv")
    
    # Load data
    if not scanner.load_data():
        logger.error("Failed to load data. Exiting.")
        return
    
    # Execute scan
    fraud_reports = scanner.scan()
    
    # Print summary
    summary = scanner.get_summary()
    print("\n" + "="*60)
    print("📊 CIVIL REGISTRY FRAUD SCAN REPORT")
    print("="*60)
    print(f"Total Records Scanned: {summary['total_records_scanned']}")
    print(f"Flagged Records: {summary['total_flagged']} ({summary['flag_rate']})")
    print("\n📋 Rule Breakdown:")
    for rule_id, data in summary.get('rule_breakdown', {}).items():
        print(f"  • {data['name']}: {data['count']} flags")
    print("\n⚠️ Risk Distribution:")
    for level, count in summary.get('risk_distribution', {}).items():
        print(f"  • {level.upper()}: {count}")
    print("="*60)
    
    # Export to JSON
    scanner.export_json("fraud_report.json")
    
    # Show top 5 highest risk cases
    if fraud_reports:
        print("\n🚨 TOP 5 HIGHEST RISK CASES:")
        sorted_reports = sorted(fraud_reports, key=lambda x: x.total_risk_score, reverse=True)[:5]
        for i, report in enumerate(sorted_reports, 1):
            print(f"\n{i}. {report.beneficiary_id} - {report.name}")
            print(f"   Risk Score: {report.total_risk_score}")
            print(f"   Flags: {[f['rule_id'] for f in report.flags]}")


if __name__ == "__main__":
    main()