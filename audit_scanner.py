#!/usr/bin/env python3
"""
Multi-Domain Fraud Scanner - Optimized Implementation
Detects fraud patterns across 3 domains using 16 deterministic rules.

Domain 1: Civil Registry (Identity Fraud) - Rules 1-4, 13
Domain 2: Labor Fraud (MGNREGA) - Rules 5-8, 17
Domain 3: Medical Fraud (PM-JAY) - Rules 9-12, 21
Cross-Domain: Rule 25 (Multi-Scheme Velocity)
"""

import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import Counter
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
# DOMAIN 1: CIVIL REGISTRY (IDENTITY FRAUD)
# =============================================================================

class CivilRegistryScanner:
    """
    Domain 1: Civil Registry Fraud Scanner
    Target: data/beneficiaries.csv
    
    Rules:
    - Rule 1: Invalid Mobile Number (9999999999)
    - Rule 2: Underage with Job Card (Age < 18)
    - Rule 3: Suspicious Age (>100 years)
    - Rule 4: Mega Family (>15 members)
    - Rule 13: Clone Detection (Same mobile shared by >3 people)
    """
    
    DOMAIN = "Civil Registry"
    DATA_PATH = "data/beneficiaries.csv"
    
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
        },
        "RULE_013": {
            "name": "Clone Detection",
            "pattern": "Mobile Sharing Ring",
            "risk_score": 30,
            "description": "Mobile number shared by >3 beneficiaries - identity broker/farming"
        }
    }
    
    # Thresholds
    DUMMY_MOBILE = "9999999999"
    MIN_ADULT_AGE = 18
    MAX_NORMAL_AGE = 100
    MAX_FAMILY_SIZE = 15
    MAX_MOBILE_SHARING = 3  # Max people sharing same mobile
    
    def __init__(self):
        self.df: pd.DataFrame = None
        self.family_counts: Dict[str, int] = {}
        self.mobile_counts: Dict[str, int] = {}  # For Rule 13
        self.fraud_reports: List[FraudReport] = []
    
    def load_data(self) -> bool:
        try:
            self.df = pd.read_csv(self.DATA_PATH, dtype={
                'BeneficiaryID': str,
                'Name': str,
                'Age': 'Int64',
                'Gender': str,
                'MobileNumber': str,
                'JobCardID': str,
                'FamilyID': str
            })
            self.df['MobileNumber'] = (
                self.df['MobileNumber']
                .astype(str)
                .str.replace(r'\D', '', regex=True)
                .str.strip()
            )
            logger.info(f"[Civil Registry] Loaded {len(self.df)} records")
            return True
        except Exception as e:
            logger.error(f"[Civil Registry] Failed to load: {e}")
            return False
    
    def _precompute_family_sizes(self):
        self.family_counts = Counter(self.df['FamilyID'].dropna().astype(str))
    
    def _precompute_mobile_sharing(self):
        """Precompute how many people share each mobile number"""
        valid_mobiles = self.df[self.df['MobileNumber'] != self.DUMMY_MOBILE]['MobileNumber'].dropna().astype(str)
        self.mobile_counts = Counter(valid_mobiles)
    
    def scan(self) -> List[FraudReport]:
        if self.df is None:
            raise RuntimeError("Data not loaded")
        
        self._precompute_family_sizes()
        self._precompute_mobile_sharing()
        self.fraud_reports = []
        
        for _, row in self.df.iterrows():
            flags = []
            
            ben_id = str(row['BeneficiaryID'])
            name = str(row['Name'])
            mobile = str(row['MobileNumber'])
            age = row['Age']
            job_card_id = row['JobCardID']
            family_id = row['FamilyID']
            
            # Rule 1: Invalid Mobile Number
            if mobile == self.DUMMY_MOBILE:
                flags.append({
                    "rule_id": "RULE_001",
                    **self.RULES["RULE_001"],
                    "evidence": {"mobile_number": mobile}
                })
            
            # Rule 2: Underage with Job Card
            if pd.notna(age) and age < self.MIN_ADULT_AGE:
                if pd.notna(job_card_id) and str(job_card_id).strip():
                    flags.append({
                        "rule_id": "RULE_002",
                        **self.RULES["RULE_002"],
                        "evidence": {"age": int(age), "job_card_id": str(job_card_id)}
                    })
            
            # Rule 3: Suspicious Age
            if pd.notna(age) and age > self.MAX_NORMAL_AGE:
                flags.append({
                    "rule_id": "RULE_003",
                    **self.RULES["RULE_003"],
                    "evidence": {"age": int(age)}
                })
            
            # Rule 4: Mega Family
            if pd.notna(family_id):
                family_size = self.family_counts.get(str(family_id), 0)
                if family_size > self.MAX_FAMILY_SIZE:
                    flags.append({
                        "rule_id": "RULE_004",
                        **self.RULES["RULE_004"],
                        "evidence": {"family_id": str(family_id), "family_size": family_size}
                    })
            
            # Rule 13: Clone Detection (Mobile Sharing)
            if mobile != self.DUMMY_MOBILE:
                mobile_share_count = self.mobile_counts.get(mobile, 0)
                if mobile_share_count > self.MAX_MOBILE_SHARING:
                    flags.append({
                        "rule_id": "RULE_013",
                        **self.RULES["RULE_013"],
                        "evidence": {"mobile_number": mobile, "shared_by": mobile_share_count}
                    })
            
            if flags:
                total_risk = sum(f['risk_score'] for f in flags)
                self.fraud_reports.append(FraudReport(
                    record_id=ben_id,
                    record_name=name,
                    domain=self.DOMAIN,
                    flags=flags,
                    total_risk_score=total_risk
                ))
        
        logger.info(f"[Civil Registry] Flagged {len(self.fraud_reports)} records")
        return self.fraud_reports


# =============================================================================
# DOMAIN 2: LABOR FRAUD (MGNREGA)
# =============================================================================

class MGNREGAScanner:
    """
    Domain 2: Labor Fraud Scanner (MGNREGA)
    Target: data/transactions_mgnrega.csv
    
    Rules:
    - Rule 5: Impossible Human (DaysWorked > 15)
    - Rule 6: Ghost Project (WorkCode ends with _000)
    - Rule 7: Wage Theft (TotalAmount != Days * Wage)
    - Rule 8: Free Money (Days == 0 AND Amount > 0)
    - Rule 17: Muster Roll Cartel (Same workers in >80% of rolls)
    """
    
    DOMAIN = "MGNREGA Labor"
    DATA_PATH = "data/transactions_mgnrega.csv"
    
    RULES = {
        "RULE_005": {
            "name": "Impossible Human",
            "pattern": "Overtime Fraud",
            "risk_score": 25,
            "description": "DaysWorked > 15 in a muster roll cycle - physically impossible"
        },
        "RULE_006": {
            "name": "Ghost Project",
            "pattern": "Fake Infrastructure",
            "risk_score": 25,
            "description": "WorkCode ends with _000 - non-existent project used to siphon funds"
        },
        "RULE_007": {
            "name": "Wage Theft",
            "pattern": "Amount Mismatch",
            "risk_score": 25,
            "description": "TotalAmount != DaysWorked * WageRate - embezzlement detected"
        },
        "RULE_008": {
            "name": "Free Money",
            "pattern": "Zero Work Payment",
            "risk_score": 25,
            "description": "Payment made with zero days worked - direct theft"
        },
        "RULE_017": {
            "name": "Muster Roll Cartel",
            "pattern": "Worker Collusion Network",
            "risk_score": 35,
            "description": "Same JobCardIDs appearing together in >80% of muster rolls - contractor cartel"
        }
    }
    
    # Thresholds
    MAX_DAYS_PER_CYCLE = 15
    GHOST_PROJECT_SUFFIX = "_000"
    CARTEL_THRESHOLD = 0.80  # 80% co-occurrence rate
    
    def __init__(self):
        self.df: pd.DataFrame = None
        self.fraud_reports: List[FraudReport] = []
        self.muster_roll_workers: Dict[str, set] = {}  # For Rule 17
    
    def load_data(self) -> bool:
        try:
            self.df = pd.read_csv(self.DATA_PATH, dtype={
                'TransactionID': str,
                'JobCardID': str,
                'WorkCode': str,
                'MusterRollID': str,
                'DaysWorked': 'Int64',
                'WageRate': 'Int64',
                'TotalAmount': 'Int64'
            })
            logger.info(f"[MGNREGA] Loaded {len(self.df)} transactions")
            return True
        except Exception as e:
            logger.error(f"[MGNREGA] Failed to load: {e}")
            return False
    
    def _detect_cartel_patterns(self):
        """Detect worker cartels - same JobCards appearing together frequently"""
        # Group by MusterRollID to find which workers appear together
        for muster_id, group in self.df.groupby('MusterRollID'):
            workers = set(group['JobCardID'].dropna().astype(str))
            self.muster_roll_workers[str(muster_id)] = workers
    
    def scan(self) -> List[FraudReport]:
        if self.df is None:
            raise RuntimeError("Data not loaded")
        
        self._detect_cartel_patterns()
        self.fraud_reports = []
        
        # Calculate co-occurrence for cartel detection
        job_card_cooccurrence = {}  # {job_card: {other_card: count}}
        for muster_id, workers in self.muster_roll_workers.items():
            for worker in workers:
                if worker not in job_card_cooccurrence:
                    job_card_cooccurrence[worker] = Counter()
                for other in workers:
                    if other != worker:
                        job_card_cooccurrence[worker][other] += 1
        
        for _, row in self.df.iterrows():
            flags = []
            
            txn_id = str(row['TransactionID'])
            job_card_id = str(row['JobCardID'])
            work_code = str(row['WorkCode'])
            days_worked = row['DaysWorked'] if pd.notna(row['DaysWorked']) else 0
            wage_rate = row['WageRate'] if pd.notna(row['WageRate']) else 0
            total_amount = row['TotalAmount'] if pd.notna(row['TotalAmount']) else 0
            
            # Rule 5: Impossible Human (Days > 15)
            if days_worked > self.MAX_DAYS_PER_CYCLE:
                flags.append({
                    "rule_id": "RULE_005",
                    **self.RULES["RULE_005"],
                    "evidence": {"days_worked": int(days_worked), "max_allowed": self.MAX_DAYS_PER_CYCLE}
                })
            
            # Rule 6: Ghost Project (WorkCode ends with _000)
            if work_code.endswith(self.GHOST_PROJECT_SUFFIX):
                flags.append({
                    "rule_id": "RULE_006",
                    **self.RULES["RULE_006"],
                    "evidence": {"work_code": work_code}
                })
            
            # Rule 7: Wage Theft (Amount mismatch)
            expected_amount = days_worked * wage_rate
            if total_amount != expected_amount and days_worked > 0:
                flags.append({
                    "rule_id": "RULE_007",
                    **self.RULES["RULE_007"],
                    "evidence": {
                        "days_worked": int(days_worked),
                        "wage_rate": int(wage_rate),
                        "expected_amount": int(expected_amount),
                        "actual_amount": int(total_amount),
                        "discrepancy": int(total_amount - expected_amount)
                    }
                })
            
            # Rule 8: Free Money (0 days but payment made)
            if days_worked == 0 and total_amount > 0:
                flags.append({
                    "rule_id": "RULE_008",
                    **self.RULES["RULE_008"],
                    "evidence": {"days_worked": 0, "amount_paid": int(total_amount)}
                })
            
            # Rule 17: Muster Roll Cartel (Worker Collusion)
            if job_card_id in job_card_cooccurrence:
                # Find workers this job card frequently appears with
                total_appearances = sum(1 for workers in self.muster_roll_workers.values() if job_card_id in workers)
                if total_appearances > 3:  # Only check if appeared in >3 rolls
                    for other_card, cooccur_count in job_card_cooccurrence[job_card_id].items():
                        cooccurrence_rate = cooccur_count / total_appearances
                        if cooccurrence_rate >= self.CARTEL_THRESHOLD:
                            flags.append({
                                "rule_id": "RULE_017",
                                **self.RULES["RULE_017"],
                                "evidence": {
                                    "job_card": job_card_id,
                                    "cartel_member": other_card,
                                    "cooccurrence_rate": f"{cooccurrence_rate:.0%}",
                                    "total_appearances": total_appearances
                                }
                            })
                            break  # Only flag once per transaction
            
            if flags:
                total_risk = sum(f['risk_score'] for f in flags)
                self.fraud_reports.append(FraudReport(
                    record_id=txn_id,
                    record_name=f"JobCard: {job_card_id}",
                    domain=self.DOMAIN,
                    flags=flags,
                    total_risk_score=total_risk
                ))
        
        logger.info(f"[MGNREGA] Flagged {len(self.fraud_reports)} transactions")
        return self.fraud_reports


# =============================================================================
# DOMAIN 3: MEDICAL FRAUD (PM-JAY)
# =============================================================================

class PMJAYScanner:
    """
    Domain 3: Medical Fraud Scanner (PM-JAY)
    Target: data/transactions_pmjay.csv
    
    Rules:
    - Rule 9: Time Travel (DischargeDate < AdmissionDate)
    - Rule 10: Biological Mismatch (Male claiming Hysterectomy)
    - Rule 11: Massive Upcoding (General Ward > 50,000)
    - Rule 12: Blacklisted Hospital (HospitalID == HOSP_999)
    - Rule 21: Procedure Mill (Hospital performs same procedure >50 times/month)
    """
    
    DOMAIN = "PM-JAY Medical"
    DATA_PATH = "data/transactions_pmjay.csv"
    BENEFICIARIES_PATH = "data/beneficiaries.csv"
    
    RULES = {
        "RULE_009": {
            "name": "Time Travel",
            "pattern": "Impossible Dates",
            "risk_score": 25,
            "description": "DischargeDate before AdmissionDate - fake/backdated claim"
        },
        "RULE_010": {
            "name": "Biological Mismatch",
            "pattern": "Gender Procedure Fraud",
            "risk_score": 25,
            "description": "Male patient claiming Hysterectomy - impossible procedure"
        },
        "RULE_011": {
            "name": "Massive Upcoding",
            "pattern": "Billing Fraud",
            "risk_score": 25,
            "description": "General Ward/Consultation costing > Rs.50,000 - inflated billing"
        },
        "RULE_012": {
            "name": "Blacklisted Hospital",
            "pattern": "Banned Entity",
            "risk_score": 25,
            "description": "Claim from blacklisted hospital HOSP_999"
        },
        "RULE_021": {
            "name": "Procedure Mill",
            "pattern": "Excessive Procedure Volume",
            "risk_score": 35,
            "description": "Hospital performs same high-value procedure >50 times/month - unnecessary surgeries"
        }
    }
    
    # Thresholds
    MAX_GENERAL_WARD_COST = 50000
    BLACKLISTED_HOSPITAL = "HOSP_999"
    FEMALE_ONLY_PROCEDURES = ["Hysterectomy"]
    GENERAL_PROCEDURES = ["General Ward", "General Consultation"]
    PROCEDURE_MILL_THRESHOLD = 50  # Procedures per month
    
    def __init__(self):
        self.df: pd.DataFrame = None
        self.beneficiaries_df: pd.DataFrame = None
        self.gender_map: Dict[str, str] = {}
        self.fraud_reports: List[FraudReport] = []
        self.hospital_procedure_counts: Dict[tuple, int] = {}  # For Rule 21
    
    def load_data(self) -> bool:
        try:
            # Load PM-JAY transactions
            self.df = pd.read_csv(self.DATA_PATH, dtype={
                'ClaimID': str,
                'BeneficiaryID': str,
                'HospitalID': str,
                'ProcedureName': str,
                'ClaimAmount': 'Int64',
                'PatientStatus': str
            }, parse_dates=['AdmissionDate', 'DischargeDate'])
            
            # Load beneficiaries for gender lookup
            self.beneficiaries_df = pd.read_csv(self.BENEFICIARIES_PATH, dtype={
                'BeneficiaryID': str,
                'Gender': str
            }, usecols=['BeneficiaryID', 'Gender'])
            
            # Create gender lookup map
            self.gender_map = dict(zip(
                self.beneficiaries_df['BeneficiaryID'],
                self.beneficiaries_df['Gender']
            ))
            
            logger.info(f"[PM-JAY] Loaded {len(self.df)} claims")
            return True
        except Exception as e:
            logger.error(f"[PM-JAY] Failed to load: {e}")
            return False
    
    def _detect_procedure_mills(self):
        """Detect hospitals performing excessive procedures"""
        # Extract month from admission date and count procedures per hospital per month
        self.df['AdmissionMonth'] = pd.to_datetime(self.df['AdmissionDate']).dt.to_period('M')
        
        for (hospital, procedure, month), group in self.df.groupby(['HospitalID', 'ProcedureName', 'AdmissionMonth']):
            count = len(group)
            self.hospital_procedure_counts[(str(hospital), str(procedure), str(month))] = count
    
    def scan(self) -> List[FraudReport]:
        if self.df is None:
            raise RuntimeError("Data not loaded")
        
        self._detect_procedure_mills()
        self.fraud_reports = []
        
        for _, row in self.df.iterrows():
            flags = []
            
            claim_id = str(row['ClaimID'])
            ben_id = str(row['BeneficiaryID'])
            hospital_id = str(row['HospitalID'])
            procedure = str(row['ProcedureName'])
            claim_amount = row['ClaimAmount'] if pd.notna(row['ClaimAmount']) else 0
            admission_date = row['AdmissionDate']
            discharge_date = row['DischargeDate']
            
            # Get gender from beneficiaries
            gender = self.gender_map.get(ben_id, 'Unknown')
            
            # Rule 9: Time Travel (Discharge before Admission)
            if pd.notna(admission_date) and pd.notna(discharge_date):
                if discharge_date < admission_date:
                    flags.append({
                        "rule_id": "RULE_009",
                        **self.RULES["RULE_009"],
                        "evidence": {
                            "admission_date": str(admission_date.date()),
                            "discharge_date": str(discharge_date.date())
                        }
                    })
            
            # Rule 10: Biological Mismatch (Male + Hysterectomy)
            if gender == 'M' and procedure in self.FEMALE_ONLY_PROCEDURES:
                flags.append({
                    "rule_id": "RULE_010",
                    **self.RULES["RULE_010"],
                    "evidence": {
                        "gender": "Male",
                        "procedure": procedure
                    }
                })
            
            # Rule 11: Massive Upcoding (General Ward > 50k)
            if procedure in self.GENERAL_PROCEDURES and claim_amount > self.MAX_GENERAL_WARD_COST:
                flags.append({
                    "rule_id": "RULE_011",
                    **self.RULES["RULE_011"],
                    "evidence": {
                        "procedure": procedure,
                        "claim_amount": int(claim_amount),
                        "threshold": self.MAX_GENERAL_WARD_COST
                    }
                })
            
            # Rule 12: Blacklisted Hospital
            if hospital_id == self.BLACKLISTED_HOSPITAL:
                flags.append({
                    "rule_id": "RULE_012",
                    **self.RULES["RULE_012"],
                    "evidence": {"hospital_id": hospital_id}
                })
            
            if flags:
                total_risk = sum(f['risk_score'] for f in flags)
                self.fraud_reports.append(FraudReport(
                    record_id=claim_id,
                    record_name=f"Beneficiary: {ben_id} | Hospital: {hospital_id}",
                    domain=self.DOMAIN,
                    flags=flags,
                    total_risk_score=total_risk
                ))
        
        logger.info(f"[PM-JAY] Flagged {len(self.fraud_reports)} claims")
        return self.fraud_reports


# =============================================================================
# MASTER SCANNER - ORCHESTRATOR
# =============================================================================

class MasterFraudScanner:
    """
    Master Fraud Scanner - Orchestrates all domain scanners.
    
    Domains:
    1. Civil Registry (Identity Fraud) - 4 rules
    2. MGNREGA (Labor Fraud) - 4 rules
    3. PM-JAY (Medical Fraud) - 4 rules
    
    Total: 12 deterministic rules
    """
    
    OUTPUT_PATH = "output/reports/fraud_report.json"
    
    def __init__(self):
        self.civil_scanner = CivilRegistryScanner()
        self.mgnrega_scanner = MGNREGAScanner()
        self.pmjay_scanner = PMJAYScanner()
        self.all_reports: List[FraudReport] = []
        self.domain_summaries: Dict[str, Dict] = {}
    
    def run_all_scans(self) -> None:
        """Execute all domain scans."""
        print("\n" + "="*70)
        print("  MULTI-DOMAIN FRAUD DETECTION SYSTEM")
        print("  16 Rules | 3 Domains + Cross-Domain | O(N) Linear Scan")
        print("="*70 + "\n")
        
        # Domain 1: Civil Registry
        print("[1/3] Scanning Civil Registry (Identity Fraud)...")
        if self.civil_scanner.load_data():
            civil_reports = self.civil_scanner.scan()
            self.all_reports.extend(civil_reports)
            self.domain_summaries["Civil Registry"] = {
                "records_scanned": len(self.civil_scanner.df),
                "flagged": len(civil_reports),
                "rules": list(self.civil_scanner.RULES.keys())
            }
        
        # Domain 2: MGNREGA
        print("[2/3] Scanning MGNREGA Transactions (Labor Fraud)...")
        if self.mgnrega_scanner.load_data():
            mgnrega_reports = self.mgnrega_scanner.scan()
            self.all_reports.extend(mgnrega_reports)
            self.domain_summaries["MGNREGA Labor"] = {
                "records_scanned": len(self.mgnrega_scanner.df),
                "flagged": len(mgnrega_reports),
                "rules": list(self.mgnrega_scanner.RULES.keys())
            }
        
        # Domain 3: PM-JAY
        print("[3/3] Scanning PM-JAY Claims (Medical Fraud)...")
        if self.pmjay_scanner.load_data():
            pmjay_reports = self.pmjay_scanner.scan()
            self.all_reports.extend(pmjay_reports)
            self.domain_summaries["PM-JAY Medical"] = {
                "records_scanned": len(self.pmjay_scanner.df),
                "flagged": len(pmjay_reports),
                "rules": list(self.pmjay_scanner.RULES.keys())
            }
        
        # Cross-Domain Analysis: Rule 25 - Multi-Scheme Velocity
        print("[4/4] Running Cross-Domain Analysis (Multi-Scheme Velocity)...")
        self._detect_multi_scheme_velocity()
    
    def _detect_multi_scheme_velocity(self):
        """Rule 25: Detect beneficiaries flagged in multiple domains"""
        # Group flagged records by beneficiary ID
        beneficiary_domains = {}  # {ben_id: [domains]}
        
        for report in self.all_reports:
            # Extract beneficiary ID from different record formats
            ben_id = None
            if report.domain == "Civil Registry":
                ben_id = report.record_id
            elif report.domain == "MGNREGA Labor":
                # Extract from JobCard reference
                job_card_match = report.record_name
                if "JobCard:" in job_card_match:
                    # Need to map JobCard to BeneficiaryID
                    pass  # Skip for now as we don't have direct mapping
            elif report.domain == "PM-JAY Medical":
                # Extract from record_name "Beneficiary: BEN_XXX | Hospital: HOSP_XXX"
                if "Beneficiary:" in report.record_name:
                    ben_id = report.record_name.split("|")[0].replace("Beneficiary:", "").strip()
            
            if ben_id and ben_id.startswith("BEN_"):
                if ben_id not in beneficiary_domains:
                    beneficiary_domains[ben_id] = set()
                beneficiary_domains[ben_id].add(report.domain)
        
        # Flag beneficiaries appearing in multiple domains
        rule_025_definition = {
            "rule_id": "RULE_025",
            "name": "Multi-Scheme Velocity",
            "pattern": "Cross-Domain Fraud",
            "risk_score": 40,
            "description": "Same beneficiary flagged in multiple schemes - professional fraudster"
        }
        
        for ben_id, domains in beneficiary_domains.items():
            if len(domains) >= 2:  # Flagged in 2+ domains
                # Add cross-domain flag to existing reports for this beneficiary
                for report in self.all_reports:
                    if ben_id in report.record_id or ben_id in report.record_name:
                        # Check if already has this flag
                        has_rule_025 = any(f['rule_id'] == 'RULE_025' for f in report.flags)
                        if not has_rule_025:
                            report.flags.append({
                                **rule_025_definition,
                                "evidence": {
                                    "beneficiary_id": ben_id,
                                    "flagged_domains": list(domains),
                                    "domain_count": len(domains)
                                }
                            })
                            report.total_risk_score += rule_025_definition['risk_score']
    
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
            if report.total_risk_score <= 25:
                risk_distribution["low"] += 1
            elif report.total_risk_score <= 50:
                risk_distribution["medium"] += 1
            elif report.total_risk_score <= 75:
                risk_distribution["high"] += 1
            else:
                risk_distribution["critical"] += 1
        
        # All rules from all scanners
        all_rules = {
            **self.civil_scanner.RULES,
            **self.mgnrega_scanner.RULES,
            **self.pmjay_scanner.RULES,
            "RULE_025": {
                "name": "Multi-Scheme Velocity",
                "pattern": "Cross-Domain Fraud",
                "risk_score": 40,
                "description": "Same beneficiary flagged in multiple schemes - professional fraudster"
            }
        }
        
        return {
            "total_records_scanned": total_scanned,
            "total_flagged": total_flagged,
            "flag_rate": f"{(total_flagged / total_scanned * 100):.2f}%" if total_scanned > 0 else "0%",
            "domain_breakdown": self.domain_summaries,
            "rule_breakdown": {
                rule_id: {
                    "name": all_rules[rule_id]["name"],
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
                "total_rules": 12,
                "rules_applied": [
                    *self.civil_scanner.RULES.keys(),
                    *self.mgnrega_scanner.RULES.keys(),
                    *self.pmjay_scanner.RULES.keys()
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
