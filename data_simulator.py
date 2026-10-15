#!/usr/bin/env python3
"""
Synthetic Data Generator with Real-Life Fraud Pattern Contamination
Generates realistic datasets with intentionally injected fraud patterns matching all 12 detection rules.

Domains:
1. Civil Registry (beneficiaries.csv) - Rules 1-4
2. MGNREGA Labor (transactions_mgnrega.csv) - Rules 5-8
3. PM-JAY Medical (transactions_pmjay.csv) - Rules 9-12

Fraud Contamination Rate: Configurable per rule
"""

import pandas as pd
import random
import sys
from faker import Faker
from datetime import datetime, timedelta
import json
from pathlib import Path

# Initialize Faker for Indian context
fake = Faker('en_IN')
Faker.seed(42)  # For reproducibility
random.seed(42)

# Make the ``src`` package importable so ids are built from the shared config seed.
_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from fraud.simulate import aadhaar_hash, make_rng  # noqa: E402

# =============================================================================
# CONFIGURATION
# =============================================================================

# Dataset Sizes
NUM_BENEFICIARIES = 2000
NUM_MGNREGA_TXNS = 5000
NUM_PMJAY_TXNS = 3000

# Fraud Contamination Rates (% of records that will be fraudulent per rule)
FRAUD_RATES = {
    # Domain 1: Civil Registry
    'RULE_001_INVALID_MOBILE': 0.05,      # 5% dummy mobiles
    'RULE_002_UNDERAGE_JOBCARD': 0.03,    # 3% minors with job cards
    'RULE_003_SUSPICIOUS_AGE': 0.02,      # 2% age > 100
    'RULE_004_MEGA_FAMILY': 0.04,         # 4% mega families
    'RULE_013_CLONE_DETECTION': 0.06,     # 6% mobile sharing (groups of 4-8 people)
    
    # Domain 2: MGNREGA
    'RULE_005_IMPOSSIBLE_HUMAN': 0.06,    # 6% days > 15
    'RULE_006_GHOST_PROJECT': 0.05,       # 5% work codes ending _000
    'RULE_007_WAGE_THEFT': 0.08,          # 8% amount mismatches
    'RULE_008_FREE_MONEY': 0.04,          # 4% zero work payments
    'RULE_017_MUSTER_CARTEL': 0.05,       # 5% cartel workers (groups appearing together)
    
    # Domain 3: PM-JAY
    'RULE_009_TIME_TRAVEL': 0.03,         # 3% discharge before admission
    'RULE_010_BIO_MISMATCH': 0.02,        # 2% male hysterectomy
    'RULE_011_MASSIVE_UPCODING': 0.05,    # 5% general ward > 50k
    'RULE_012_BLACKLISTED_HOSPITAL': 0.04,# 4% HOSP_999 claims
    'RULE_021_PROCEDURE_MILL': 0.06,      # 6% hospitals doing excessive procedures
    
    # Cross-Domain
    'RULE_025_MULTI_SCHEME': 0.02         # 2% beneficiaries in multiple domains
}

# Create output directories
Path("data").mkdir(exist_ok=True)
Path("output/reports").mkdir(parents=True, exist_ok=True)

print("🚀 Starting Synthetic Data Generation with Fraud Contamination...")
print(f"   Total Fraud Injection Points: {len(FRAUD_RATES)} rules")
print(f"   Average Contamination Rate: {sum(FRAUD_RATES.values()) / len(FRAUD_RATES) * 100:.1f}%\n")


# =============================================================================
# DOMAIN 1: CIVIL REGISTRY (BENEFICIARIES)
# =============================================================================

def generate_beneficiaries():
    """Generate beneficiaries with Rules 1-4, 13 fraud patterns"""
    print(f"📋 Generating {NUM_BENEFICIARIES} Beneficiaries (Civil Registry)...")
    
    beneficiaries = []
    aadhaar_rng = make_rng()  # deterministic Aadhaar hashes (seeded)

    # Create family pool (for mega family fraud)
    num_families = int(NUM_BENEFICIARIES / 5)
    family_ids = [f"FAM_{i:05d}" for i in range(num_families)]
    
    # Track fraud injections
    fraud_tracker = {rule: 0 for rule in ['RULE_001', 'RULE_002', 'RULE_003', 'RULE_004', 'RULE_013']}
    
    # Pre-select mega family
    mega_family_id = family_ids[0]
    mega_family_size = int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_004_MEGA_FAMILY'])
    
    # RULE_013: Clone Detection - Create mobile sharing groups
    num_clone_groups = int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_013_CLONE_DETECTION'] / 5)  # Groups of ~5
    clone_mobiles = [f"99{random.randint(10000000, 99999999)}" for _ in range(num_clone_groups)]
    clone_assignments = []  # Track who gets clone mobiles
    
    for i in range(NUM_BENEFICIARIES):
        ben_id = f"BEN_{10000 + i}"
        name = fake.name()
        
        # Default values
        age = random.randint(18, 90)
        gender = random.choice(['M', 'F', 'O'])
        mobile = fake.phone_number().replace('-', '').replace(' ', '')[:10]
        job_card_id = f"JC_{random.randint(100000, 999999)}" if random.random() > 0.3 else None
        
        # Assign family
        if i < mega_family_size:
            family_id = mega_family_id  # RULE_004: Mega Family
            fraud_tracker['RULE_004'] += 1
        else:
            family_id = random.choice(family_ids)
        
        # RULE_001: Invalid Mobile Number (9999999999)
        if random.random() < FRAUD_RATES['RULE_001_INVALID_MOBILE']:
            mobile = "9999999999"
            fraud_tracker['RULE_001'] += 1
        # RULE_013: Clone Detection (Mobile Sharing)
        elif i < len(clone_mobiles) * 5:  # Assign clone mobiles to first N beneficiaries
            mobile = clone_mobiles[i // 5]  # 5 people share same mobile
            fraud_tracker['RULE_013'] += 1
            clone_assignments.append(ben_id)
        
        # RULE_002: Underage with Job Card
        if random.random() < FRAUD_RATES['RULE_002_UNDERAGE_JOBCARD']:
            age = random.randint(5, 17)
            job_card_id = f"JC_{random.randint(100000, 999999)}"
            fraud_tracker['RULE_002'] += 1
        
        # RULE_003: Suspicious Age (>100)
        if random.random() < FRAUD_RATES['RULE_003_SUSPICIOUS_AGE']:
            age = random.randint(101, 150)
            fraud_tracker['RULE_003'] += 1
        
        beneficiaries.append({
            'BeneficiaryID': ben_id,
            'Name': name,
            'Age': age,
            'Gender': gender,
            'MobileNumber': mobile,
            'AadhaarHash': aadhaar_hash(aadhaar_rng),
            'FamilyID': family_id,
            'District': random.choice(['Ghotala', 'Bharpur', 'Naqli Nagar']),
            'JobCardID': job_card_id
        })
    
    df = pd.DataFrame(beneficiaries)
    df.to_csv('data/beneficiaries.csv', index=False)
    
    print(f"   ✅ beneficiaries.csv created")
    print(f"      Fraud injections: {fraud_tracker}")
    return df


# =============================================================================
# DOMAIN 2: MGNREGA LABOR (TRANSACTIONS)
# =============================================================================

def generate_mgnrega_transactions(df_beneficiaries):
    """Generate MGNREGA transactions with Rules 5-8, 17 fraud patterns"""
    print(f"\n🔨 Generating {NUM_MGNREGA_TXNS} MGNREGA Transactions (Labor Fraud)...")
    
    transactions = []
    valid_job_cards = df_beneficiaries[df_beneficiaries['JobCardID'].notna()]['JobCardID'].tolist()
    
    fraud_tracker = {rule: 0 for rule in ['RULE_005', 'RULE_006', 'RULE_007', 'RULE_008', 'RULE_017']}
    
    # RULE_017: Create cartel worker groups (same workers appearing together)
    num_cartel_groups = int(len(valid_job_cards) * FRAUD_RATES['RULE_017_MUSTER_CARTEL'] / 8)
    cartel_groups = []
    for _ in range(num_cartel_groups):
        cartel_size = random.randint(5, 10)
        cartel_groups.append(random.sample(valid_job_cards, cartel_size))
    
    muster_roll_counter = 10000
    
    for i in range(NUM_MGNREGA_TXNS):
        txn_id = f"TXN_MGN_{i:06d}"
        
        # RULE_017: Cartel - use cartel group workers together in same muster roll
        if cartel_groups and i % 20 == 0 and i < len(cartel_groups) * 10:  # Every 20th txn, create cartel muster
            cartel_group = cartel_groups[i // 20 % len(cartel_groups)]
            muster_roll_id = f"MR_{muster_roll_counter}"
            muster_roll_counter += 1
            
            # Create multiple transactions for this cartel group in same muster roll
            for job_card in cartel_group:
                days_worked = random.randint(5, 15)
                wage_rate = 230
                work_code = f"WC_{random.randint(100, 999)}"
                
                transactions.append({
                    'TransactionID': f"TXN_MGN_{i:06d}_{job_card}",
                    'JobCardID': job_card,
                    'WorkCode': work_code,
                    'MusterRollID': muster_roll_id,
                    'WorkStartDate': fake.date_between(start_date='-1y', end_date='today'),
                    'DaysWorked': days_worked,
                    'WageRate': wage_rate,
                    'TotalAmount': days_worked * wage_rate
                })
                fraud_tracker['RULE_017'] += 1
            continue
        
        job_card = random.choice(valid_job_cards)
        
        # Default values
        days_worked = random.randint(5, 15)
        wage_rate = 230  # Standard daily wage
        work_code = f"WC_{random.randint(100, 999)}"
        
        # RULE_005: Impossible Human (DaysWorked > 15)
        if random.random() < FRAUD_RATES['RULE_005_IMPOSSIBLE_HUMAN']:
            days_worked = random.randint(16, 30)
            fraud_tracker['RULE_005'] += 1
        
        # RULE_006: Ghost Project (WorkCode ends with _000)
        if random.random() < FRAUD_RATES['RULE_006_GHOST_PROJECT']:
            work_code = f"WC_{random.randint(100, 999)}_000"
            fraud_tracker['RULE_006'] += 1
        
        # Calculate expected amount
        expected_amount = days_worked * wage_rate
        total_amount = expected_amount
        
        # RULE_007: Wage Theft (Amount != Days * Wage)
        if random.random() < FRAUD_RATES['RULE_007_WAGE_THEFT']:
            # Introduce random discrepancy
            discrepancy = random.randint(-2000, 5000)
            total_amount = expected_amount + discrepancy
            fraud_tracker['RULE_007'] += 1
        
        # RULE_008: Free Money (Days = 0 but Amount > 0)
        if random.random() < FRAUD_RATES['RULE_008_FREE_MONEY']:
            days_worked = 0
            total_amount = random.randint(1000, 5000)
            fraud_tracker['RULE_008'] += 1
        
        transactions.append({
            'TransactionID': txn_id,
            'JobCardID': job_card,
            'WorkCode': work_code,
            'MusterRollID': f"MR_{random.randint(10000, 99999)}",
            'WorkStartDate': fake.date_between(start_date='-1y', end_date='today'),
            'DaysWorked': days_worked,
            'WageRate': wage_rate,
            'TotalAmount': total_amount
        })
    
    df = pd.DataFrame(transactions)
    df.to_csv('data/transactions_mgnrega.csv', index=False)
    
    print(f"   ✅ transactions_mgnrega.csv created")
    print(f"      Fraud injections: {fraud_tracker}")
    return df


# =============================================================================
# DOMAIN 3: PM-JAY MEDICAL (CLAIMS)
# =============================================================================

def generate_pmjay_transactions(df_beneficiaries):
    """Generate PM-JAY claims with Rules 9-12, 21 fraud patterns"""
    print(f"\n🏥 Generating {NUM_PMJAY_TXNS} PM-JAY Medical Claims (Medical Fraud)...")
    
    claims = []
    ben_ids = df_beneficiaries['BeneficiaryID'].tolist()
    
    # Get gender mapping for biological mismatch detection
    gender_map = dict(zip(df_beneficiaries['BeneficiaryID'], df_beneficiaries['Gender']))
    
    fraud_tracker = {rule: 0 for rule in ['RULE_009', 'RULE_010', 'RULE_011', 'RULE_012', 'RULE_021']}
    
    # Procedure options
    procedures = {
        'general': ['General Ward', 'General Consultation'],
        'surgery': ['Cataract Surgery', 'Appendectomy', 'Hernia Repair'],
        'female_only': ['Hysterectomy', 'C-Section'],
        'expensive': ['Cardiac Surgery', 'Kidney Transplant', 'Dialysis']
    }
    
    # RULE_021: Create procedure mill hospitals (same procedure many times)
    mill_hospitals = [f"HOSP_{random.randint(1, 10):03d}" for _ in range(3)]  # 3 mill hospitals
    mill_procedures = [random.choice(procedures['surgery']) for _ in mill_hospitals]
    
    for i in range(NUM_PMJAY_TXNS):
        claim_id = f"CLM_{i:06d}"
        
        # RULE_021: Procedure Mill - assign many claims to mill hospitals with same procedure
        if random.random() < FRAUD_RATES['RULE_021_PROCEDURE_MILL']:
            mill_idx = i % len(mill_hospitals)
            hospital_id = mill_hospitals[mill_idx]
            procedure = mill_procedures[mill_idx]
            ben_id = random.choice(ben_ids)
            gender = gender_map.get(ben_id, 'M')
            fraud_tracker['RULE_021'] += 1
        # RULE_010: Biological Mismatch (Male claiming Hysterectomy)
        elif random.random() < FRAUD_RATES['RULE_010_BIO_MISMATCH']:
            male_beneficiaries = [bid for bid, g in gender_map.items() if g == 'M']
            if male_beneficiaries:
                ben_id = random.choice(male_beneficiaries)
                gender = 'M'
                procedure = random.choice(procedures['female_only'])
                fraud_tracker['RULE_010'] += 1
            else:
                ben_id = random.choice(ben_ids)
                gender = gender_map.get(ben_id, 'M')
                proc_category = random.choice(['general', 'surgery', 'expensive'])
                procedure = random.choice(procedures[proc_category])
        else:
            ben_id = random.choice(ben_ids)
            gender = gender_map.get(ben_id, 'M')
            proc_category = random.choice(['general', 'surgery', 'expensive'])
            procedure = random.choice(procedures[proc_category])
        
        # Default values
        admission_date = fake.date_between(start_date='-1y', end_date='today')
        discharge_date = admission_date + timedelta(days=random.randint(1, 10))
        hospital_id = f"HOSP_{random.randint(1, 50):03d}"
        
        # Set realistic claim amount based on procedure
        if procedure in procedures['general']:
            claim_amount = random.randint(5000, 30000)
        elif procedure in procedures['female_only'] or procedure in procedures['surgery']:
            claim_amount = random.randint(30000, 100000)
        else:
            claim_amount = random.randint(100000, 500000)
        
        # RULE_009: Time Travel (DischargeDate < AdmissionDate)
        if random.random() < FRAUD_RATES['RULE_009_TIME_TRAVEL']:
            discharge_date = admission_date - timedelta(days=random.randint(1, 10))
            fraud_tracker['RULE_009'] += 1
        
        # RULE_011: Massive Upcoding (General procedures > 50,000)
        if random.random() < FRAUD_RATES['RULE_011_MASSIVE_UPCODING']:
            procedure = random.choice(procedures['general'])
            claim_amount = random.randint(50001, 150000)
            fraud_tracker['RULE_011'] += 1
        
        # RULE_012: Blacklisted Hospital (HOSP_999)
        if random.random() < FRAUD_RATES['RULE_012_BLACKLISTED_HOSPITAL']:
            hospital_id = "HOSP_999"
            fraud_tracker['RULE_012'] += 1
        
        claims.append({
            'ClaimID': claim_id,
            'BeneficiaryID': ben_id,
            'HospitalID': hospital_id,
            'AdmissionDate': admission_date,
            'DischargeDate': discharge_date,
            'ProcedureName': procedure,
            'ClaimAmount': claim_amount,
            'PatientStatus': random.choice(['Discharged', 'Referred', 'Recovered'])
        })
    
    df = pd.DataFrame(claims)
    df.to_csv('data/transactions_pmjay.csv', index=False)
    
    print(f"   ✅ transactions_pmjay.csv created")
    print(f"      Fraud injections: {fraud_tracker}")
    return df


# =============================================================================
# FRAUD GROUND TRUTH REPORT
# =============================================================================

def generate_fraud_ground_truth(df_beneficiaries, df_mgnrega, df_pmjay):
    """Generate a ground truth report for ML model training/validation"""
    print(f"\n📊 Generating Fraud Ground Truth Report...")
    
    ground_truth = {
        'generation_timestamp': datetime.now().isoformat(),
        'dataset_summary': {
            'num_beneficiaries': len(df_beneficiaries),
            'num_mgnrega_transactions': len(df_mgnrega),
            'num_pmjay_claims': len(df_pmjay)
        },
        'fraud_contamination_rates': FRAUD_RATES,
        'expected_fraud_counts': {
            'RULE_001': int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_001_INVALID_MOBILE']),
            'RULE_002': int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_002_UNDERAGE_JOBCARD']),
            'RULE_003': int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_003_SUSPICIOUS_AGE']),
            'RULE_004': int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_004_MEGA_FAMILY']),
            'RULE_013': int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_013_CLONE_DETECTION']),
            'RULE_005': int(NUM_MGNREGA_TXNS * FRAUD_RATES['RULE_005_IMPOSSIBLE_HUMAN']),
            'RULE_006': int(NUM_MGNREGA_TXNS * FRAUD_RATES['RULE_006_GHOST_PROJECT']),
            'RULE_007': int(NUM_MGNREGA_TXNS * FRAUD_RATES['RULE_007_WAGE_THEFT']),
            'RULE_008': int(NUM_MGNREGA_TXNS * FRAUD_RATES['RULE_008_FREE_MONEY']),
            'RULE_017': int(NUM_MGNREGA_TXNS * FRAUD_RATES['RULE_017_MUSTER_CARTEL']),
            'RULE_009': int(NUM_PMJAY_TXNS * FRAUD_RATES['RULE_009_TIME_TRAVEL']),
            'RULE_010': int(NUM_PMJAY_TXNS * FRAUD_RATES['RULE_010_BIO_MISMATCH']),
            'RULE_011': int(NUM_PMJAY_TXNS * FRAUD_RATES['RULE_011_MASSIVE_UPCODING']),
            'RULE_012': int(NUM_PMJAY_TXNS * FRAUD_RATES['RULE_012_BLACKLISTED_HOSPITAL']),
            'RULE_021': int(NUM_PMJAY_TXNS * FRAUD_RATES['RULE_021_PROCEDURE_MILL']),
            'RULE_025': 'Cross-domain (calculated post-generation)'
        },
        'notes': 'This report shows expected fraud counts. Actual counts may vary due to random seeding.'
    }
    
    with open('output/reports/fraud_ground_truth.json', 'w') as f:
        json.dump(ground_truth, f, indent=2)
    
    print(f"   ✅ fraud_ground_truth.json created")
    
    # Calculate total excluding RULE_025 (which is cross-domain)
    total_fraud = sum(v for k, v in ground_truth['expected_fraud_counts'].items() if k != 'RULE_025')
    print(f"\n📈 Expected Total Fraud Cases: {total_fraud} (excluding cross-domain RULE_025)")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    # Generate all datasets
    df_ben = generate_beneficiaries()
    df_mgn = generate_mgnrega_transactions(df_ben)
    df_pmjay = generate_pmjay_transactions(df_ben)
    
    # Generate ground truth for ML training
    generate_fraud_ground_truth(df_ben, df_mgn, df_pmjay)
    
    print("\n" + "="*70)
    print("🎉 SYNTHETIC DATA GENERATION COMPLETE")
    print("="*70)
    print(f"✅ Generated {NUM_BENEFICIARIES} beneficiaries")
    print(f"✅ Generated {NUM_MGNREGA_TXNS} MGNREGA transactions")
    print(f"✅ Generated {NUM_PMJAY_TXNS} PM-JAY claims")
    print(f"✅ All datasets contaminated with 16 fraud patterns (Rules 1-25)")
    print(f"\n📁 Files created:")
    print(f"   - data/beneficiaries.csv")
    print(f"   - data/transactions_mgnrega.csv")
    print(f"   - data/transactions_pmjay.csv")
    print(f"   - output/reports/fraud_ground_truth.json")
    print(f"\n🔍 Next step: Run audit_scanner.py to detect the injected fraud!")
    print("="*70)