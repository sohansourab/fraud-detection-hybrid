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

import argparse
import math
import pandas as pd
import random
import sys
from dataclasses import replace
from faker import Faker
from datetime import datetime, timedelta
import json
from collections import Counter
from pathlib import Path

# Initialize Faker for Indian context
fake = Faker('en_IN')
Faker.seed(42)  # For reproducibility
random.seed(42)

# Make the ``src`` package importable so ids are built from the shared config seed.
_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from fraud.simulate import aadhaar_hash, make_rng, split_for  # noqa: E402
from fraud.config import get_config  # noqa: E402
import fraud.config as _fraud_config  # noqa: E402


def _parse_args() -> argparse.Namespace:
    """CLI overrides. Only used when run as a script (never on import)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prevalence",
        type=float,
        default=None,
        help="Override simulator.prevalence for this run (default: config value).",
    )
    return parser.parse_args()


_ARGS = _parse_args() if __name__ == "__main__" else argparse.Namespace(prevalence=None)
if _ARGS.prevalence is not None:
    # Rebuild the cached config so every get_config() call sees the override.
    _fraud_config._CONFIG = replace(
        get_config(),
        simulator=replace(get_config().simulator, prevalence=_ARGS.prevalence),
    )

# =============================================================================
# GROUND-TRUTH LABEL BOOKKEEPING
# -----------------------------------------------------------------------------
# The simulator records, per generated record, what (if anything) was injected.
# Detection code (src/fraud/rules/*, src/fraud/pipeline.py) must never read
# this: it is written out as data/labels.csv only.
# =============================================================================

# record_id -> list of (fraud_type, injected_rule_id)
INJECTIONS: dict[str, list[tuple[str, str]]] = {}
# record_id -> fraud_type  (is_fraud stays 0 - these are deliberate hard negatives)
HARD_NEGATIVES: dict[str, str] = {}
# fraud_type / rule_id -> number of injected records (actual, not estimated)
INJECTION_COUNTS: Counter = Counter()
# Cross-scheme beneficiaries injected for Rule 025 (module P2c). Populated by
# generate_beneficiaries() and consumed by the MGNREGA / PM-JAY generators.
CROSS_SCHEME: list[dict] = []

LABEL_COLUMNS = [
    "record_id",
    "domain",
    "is_fraud",
    "fraud_type",
    "injected_rule_id",
    "split",
]


def _mark_fraud(record_id: str, fraud_type: str, rule_id: str) -> None:
    """Record that ``record_id`` was injected as fraud for ``rule_id``."""
    INJECTIONS.setdefault(str(record_id), []).append((fraud_type, rule_id))
    INJECTION_COUNTS[fraud_type] += 1


def _mark_hard_negative(record_id: str, fraud_type: str) -> None:
    """Record a deliberate non-fraud hard negative (blank/null mobile)."""
    HARD_NEGATIVES[str(record_id)] = fraud_type
    INJECTION_COUNTS[fraud_type] += 1

# =============================================================================
# CONFIGURATION
# =============================================================================

# Dataset Sizes
NUM_BENEFICIARIES = 2000
NUM_MGNREGA_TXNS = 5000
NUM_PMJAY_TXNS = 3000

# Fraud Contamination Rates (% of records that will be fraudulent per rule).
# These are *relative weights*: the simulator rescales them below so the
# realised fraud rate matches ``simulator.prevalence``.
_RAW_FRAUD_RATES = {
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

# --- Prevalence scaling (module P2b) ---------------------------------------
# The raw rates above add up to a far higher fraud rate than a realistic
# welfare dataset. Scale every injected volume so the realised fraud rate
# (is_fraud=1 records / scannable records) lands near simulator.prevalence.
# Group-structured injections keep a floor so Rules 004/013/017/021 can still
# fire (a cartel needs several co-occurring rolls; a mill needs >50 claims).
SIM = get_config().simulator
_CIVIL_KEYS = (
    'RULE_001_INVALID_MOBILE', 'RULE_002_UNDERAGE_JOBCARD',
    'RULE_003_SUSPICIOUS_AGE', 'RULE_004_MEGA_FAMILY',
    'RULE_013_CLONE_DETECTION',
)
_MGNREGA_KEYS = (
    'RULE_005_IMPOSSIBLE_HUMAN', 'RULE_006_GHOST_PROJECT',
    'RULE_007_WAGE_THEFT', 'RULE_008_FREE_MONEY',
)
_PMJAY_KEYS = (
    'RULE_009_TIME_TRAVEL', 'RULE_010_BIO_MISMATCH',
    'RULE_011_MASSIVE_UPCODING', 'RULE_012_BLACKLISTED_HOSPITAL',
)
_AVG_CARTEL_SIZE = (SIM.cartel_group_min_size + SIM.cartel_group_max_size) / 2
_SCANNABLE = NUM_BENEFICIARIES + NUM_MGNREGA_TXNS + NUM_PMJAY_TXNS
_TARGET_FRAUD = SIM.prevalence * _SCANNABLE
_EXPECTED_FRAUD = (
    NUM_BENEFICIARIES * sum(_RAW_FRAUD_RATES[k] for k in _CIVIL_KEYS)
    + NUM_MGNREGA_TXNS * sum(_RAW_FRAUD_RATES[k] for k in _MGNREGA_KEYS)
    + NUM_PMJAY_TXNS * sum(_RAW_FRAUD_RATES[k] for k in _PMJAY_KEYS)
    + SIM.cartel_groups * _AVG_CARTEL_SIZE * SIM.cartel_muster_rolls
    + SIM.procedure_mill_groups * SIM.procedure_mill_group_size
)
_SCALE = _TARGET_FRAUD / _EXPECTED_FRAUD

# Effective (scaled) per-rule rates consumed by the generators below.
FRAUD_RATES = {key: rate * _SCALE for key, rate in _RAW_FRAUD_RATES.items()}
# Structural floors so the group rules can still fire on the scaled budget.
CARTEL_GROUPS = max(1, round(SIM.cartel_groups * _SCALE))
MILL_GROUPS = max(1, round(SIM.procedure_mill_groups * _SCALE))
MILL_GROUP_SIZE = max(
    get_config().pmjay.procedure_mill_threshold + 1,
    round(SIM.procedure_mill_group_size * _SCALE),
)

# Create output directories
Path("data").mkdir(exist_ok=True)
Path("output/reports").mkdir(parents=True, exist_ok=True)

print("🚀 Starting Synthetic Data Generation with Fraud Contamination...")
print(f"   Total Fraud Injection Points: {len(FRAUD_RATES)} rules")
print(f"   Target prevalence: {SIM.prevalence:.0%} (scale factor {_SCALE:.4f})")
print(f"   Structural floors: cartel_groups={CARTEL_GROUPS}, mill={MILL_GROUPS}x{MILL_GROUP_SIZE}\n")


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
    mega_family_size = max(
        int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_004_MEGA_FAMILY']),
        get_config().civil_registry.max_family_size + 1,  # keep Rule 004 able to fire
    )
    
    # RULE_013: Clone Detection - Create mobile sharing groups
    num_clone_groups = max(
        1,  # keep Rule 013 able to fire on the scaled budget
        int(NUM_BENEFICIARIES * FRAUD_RATES['RULE_013_CLONE_DETECTION'] / 5),
    )  # Groups of ~5
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
            _mark_fraud(ben_id, 'mega_family', 'RULE_004')
        else:
            family_id = random.choice(family_ids)
        
        # RULE_001: Invalid Mobile Number (9999999999)
        if random.random() < FRAUD_RATES['RULE_001_INVALID_MOBILE']:
            mobile = "9999999999"
            fraud_tracker['RULE_001'] += 1
            _mark_fraud(ben_id, 'invalid_mobile', 'RULE_001')
        # RULE_013: Clone Detection (Mobile Sharing)
        elif i < len(clone_mobiles) * 5:  # Assign clone mobiles to first N beneficiaries
            mobile = clone_mobiles[i // 5]  # 5 people share same mobile
            fraud_tracker['RULE_013'] += 1
            clone_assignments.append(ben_id)
            _mark_fraud(ben_id, 'mobile_sharing', 'RULE_013')
        
        # RULE_002: Underage with Job Card
        if random.random() < FRAUD_RATES['RULE_002_UNDERAGE_JOBCARD']:
            age = random.randint(5, 17)
            job_card_id = f"JC_{random.randint(100000, 999999)}"
            fraud_tracker['RULE_002'] += 1
            _mark_fraud(ben_id, 'underage_jobcard', 'RULE_002')
        
        # RULE_003: Suspicious Age (>100)
        if random.random() < FRAUD_RATES['RULE_003_SUSPICIOUS_AGE']:
            age = random.randint(101, 150)
            fraud_tracker['RULE_003'] += 1
            _mark_fraud(ben_id, 'suspicious_age', 'RULE_003')
        
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
    
    # RULE_013 hard negatives: ~blank_mobile_rate of *clean* beneficiaries get a
    # null or blank mobile. These are missing data, not shared identity, so the
    # rule must ignore them and they are labeled is_fraud=0.
    blank_rate = get_config().simulator.blank_mobile_rate
    clean_idx = [
        i for i, row in enumerate(beneficiaries)
        if row['BeneficiaryID'] not in INJECTIONS
    ]
    num_blank = min(len(clean_idx), int(NUM_BENEFICIARIES * blank_rate))
    blank_rng = make_rng(get_config().seed + 100)
    for pos, idx in enumerate(blank_rng.sample(clean_idx, num_blank)):
        beneficiaries[idx]['MobileNumber'] = None if pos % 2 == 0 else ''
        _mark_hard_negative(
            beneficiaries[idx]['BeneficiaryID'], 'hard_negative_blank_mobile'
        )

    # --- P2c: dedicated cross-scheme injection for Rule 025 ------------------
    # Each injected beneficiary is placed (and *flagged*) in every scheme in its
    # combo, so Rule 025 has a real multi-scheme basis. The Civil event is the
    # beneficiary row itself (underage + job card -> Rule 002); MGNREGA / PM-JAY
    # events are added by the downstream generators using the exact ids below.
    cs_cfg = get_config().simulator.cross_scheme
    cs_rng = make_rng(get_config().seed + 200)
    for i in range(cs_cfg.beneficiaries):
        combo = list(cs_cfg.combos[i % len(cs_cfg.combos)])
        ben_id = f"BEN_CS_{i:04d}"
        job_card = f"JC_CS_{i:04d}"
        in_civil = "Civil Registry" in combo
        beneficiaries.append({
            'BeneficiaryID': ben_id,
            'Name': fake.name(),
            'Age': cs_rng.randint(5, 17) if in_civil else cs_rng.randint(18, 90),
            'Gender': cs_rng.choice(['M', 'F', 'O']),
            'MobileNumber': f"98{cs_rng.randint(10000000, 99999999)}",
            'AadhaarHash': aadhaar_hash(aadhaar_rng),
            'FamilyID': f"FAM_CS_{i:04d}",
            'District': cs_rng.choice(['Ghotala', 'Bharpur', 'Naqli Nagar']),
            'JobCardID': job_card,
        })
        CROSS_SCHEME.append({'ben_id': ben_id, 'job_card': job_card, 'combo': combo})
        if in_civil:
            _mark_fraud(ben_id, 'cross_scheme', 'RULE_025')

    df = pd.DataFrame(beneficiaries)
    df.to_csv('data/beneficiaries.csv', index=False)
    
    print(f"   ✅ beneficiaries.csv created")
    print(f"      Fraud injections: {fraud_tracker}")
    return df


# =============================================================================
# DOMAIN 2: MGNREGA LABOR (TRANSACTIONS)
# =============================================================================

def _build_cartel_groups(valid_job_cards, sim):
    """Return disjoint cartel groups of size [cartel_group_min_size, cartel_group_max_size].

    Deterministic: draws group sizes and the shuffled pool from the global
    seeded RNG, so a fixed seed always yields the same groups.
    """
    num_groups = max(0, CARTEL_GROUPS)
    sizes = [
        random.randint(sim.cartel_group_min_size, sim.cartel_group_max_size)
        for _ in range(num_groups)
    ]
    pool = list(valid_job_cards)
    random.shuffle(pool)
    groups = []
    cursor = 0
    for size in sizes:
        group = pool[cursor:cursor + size]
        if not group:
            break
        groups.append(group)
        cursor += size
    return groups


def generate_mgnrega_transactions(df_beneficiaries):
    """Generate MGNREGA transactions with Rules 5-8, 17 fraud patterns"""
    print(f"\n🔨 Generating {NUM_MGNREGA_TXNS} MGNREGA Transactions (Labor Fraud)...")
    
    transactions = []
    valid_job_cards = df_beneficiaries[df_beneficiaries['JobCardID'].notna()]['JobCardID'].tolist()
    
    fraud_tracker = {rule: 0 for rule in ['RULE_005', 'RULE_006', 'RULE_007', 'RULE_008', 'RULE_017']}
    
    # RULE_017: Cartel groups. Every member of a group appears together in *all*
    # cartel_muster_rolls muster rolls, and the group's job cards are reserved so
    # random transactions cannot dilute the co-occurrence rate. Members then have
    # appearances == cartel_muster_rolls (> min_cartel_appearances) and pair rate
    # == 1.0 (>= cartel_threshold), so the rule's gate passes.
    sim = get_config().simulator
    # Keep cross-scheme job cards out of the random / cartel pools so their only
    # MGNREGA appearance is the dedicated Rule 025 transaction below.
    cs_cards = {cs['job_card'] for cs in CROSS_SCHEME}
    base_pool = [card for card in valid_job_cards if card not in cs_cards] or valid_job_cards
    cartel_groups = _build_cartel_groups(base_pool, sim)
    cartel_cards = {card for group in cartel_groups for card in group}
    random_pool = [card for card in base_pool if card not in cartel_cards] or base_pool
    
    for g, cartel_group in enumerate(cartel_groups):
        for r in range(sim.cartel_muster_rolls):
            muster_roll_id = f"MR_CARTEL_{g:02d}_{r:02d}"
            for job_card in cartel_group:
                days_worked = random.randint(5, 15)
                wage_rate = 230
                work_code = f"WC_{random.randint(100, 999)}"
                txn_id = f"TXN_MGN_CARTEL_{g:02d}_{r:02d}_{job_card}"
                transactions.append({
                    'TransactionID': txn_id,
                    'JobCardID': job_card,
                    'WorkCode': work_code,
                    'MusterRollID': muster_roll_id,
                    'WorkStartDate': fake.date_between(start_date='-1y', end_date='today'),
                    'DaysWorked': days_worked,
                    'WageRate': wage_rate,
                    'TotalAmount': days_worked * wage_rate
                })
                fraud_tracker['RULE_017'] += 1
                _mark_fraud(txn_id, 'muster_cartel', 'RULE_017')
    
    for i in range(NUM_MGNREGA_TXNS):
        txn_id = f"TXN_MGN_{i:06d}"
        
        job_card = random.choice(random_pool)
        
        # Default values
        days_worked = random.randint(5, 15)
        wage_rate = 230  # Standard daily wage
        work_code = f"WC_{random.randint(100, 999)}"
        
        # RULE_005: Impossible Human (DaysWorked > 15)
        if random.random() < FRAUD_RATES['RULE_005_IMPOSSIBLE_HUMAN']:
            days_worked = random.randint(16, 30)
            fraud_tracker['RULE_005'] += 1
            _mark_fraud(txn_id, 'impossible_human', 'RULE_005')
        
        # RULE_006: Ghost Project (WorkCode ends with _000)
        if random.random() < FRAUD_RATES['RULE_006_GHOST_PROJECT']:
            work_code = f"WC_{random.randint(100, 999)}_000"
            fraud_tracker['RULE_006'] += 1
            _mark_fraud(txn_id, 'ghost_project', 'RULE_006')
        
        # Calculate expected amount
        expected_amount = days_worked * wage_rate
        total_amount = expected_amount
        
        # RULE_007: Wage Theft (Amount != Days * Wage)
        if random.random() < FRAUD_RATES['RULE_007_WAGE_THEFT']:
            # Introduce random discrepancy
            discrepancy = random.randint(-2000, 5000)
            total_amount = expected_amount + discrepancy
            fraud_tracker['RULE_007'] += 1
            _mark_fraud(txn_id, 'wage_theft', 'RULE_007')
        
        # RULE_008: Free Money (Days = 0 but Amount > 0)
        if random.random() < FRAUD_RATES['RULE_008_FREE_MONEY']:
            days_worked = 0
            total_amount = random.randint(1000, 5000)
            fraud_tracker['RULE_008'] += 1
            _mark_fraud(txn_id, 'free_money', 'RULE_008')
        
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

    # --- P2c: cross-scheme MGNREGA events (Rule 025) -------------------------
    for cs in CROSS_SCHEME:
        if "MGNREGA Labor" not in cs['combo']:
            continue
        days_worked = get_config().mgnrega.max_days_per_cycle + 5  # Rule 005
        wage_rate = 230
        txn_id = f"TXN_MGN_CS_{cs['ben_id']}"
        transactions.append({
            'TransactionID': txn_id,
            'JobCardID': cs['job_card'],
            'WorkCode': f"WC_{random.randint(100, 999)}",
            'MusterRollID': f"MR_CS_{cs['ben_id']}",
            'WorkStartDate': fake.date_between(start_date='-1y', end_date='today'),
            'DaysWorked': days_worked,
            'WageRate': wage_rate,
            'TotalAmount': days_worked * wage_rate,
        })
        _mark_fraud(txn_id, 'cross_scheme', 'RULE_025')

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
    
    # RULE_021 procedure-mill claims are injected in one dedicated block after
    # the main loop (see below), so here only the organic rules are assigned.
    for i in range(NUM_PMJAY_TXNS):
        claim_id = f"CLM_{i:06d}"
        
        # RULE_010: Biological Mismatch (Male claiming Hysterectomy)
        if random.random() < FRAUD_RATES['RULE_010_BIO_MISMATCH']:
            male_beneficiaries = [bid for bid, g in gender_map.items() if g == 'M']
            if male_beneficiaries:
                ben_id = random.choice(male_beneficiaries)
                gender = 'M'
                procedure = random.choice(procedures['female_only'])
                fraud_tracker['RULE_010'] += 1
                _mark_fraud(claim_id, 'bio_mismatch', 'RULE_010')
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
            _mark_fraud(claim_id, 'time_travel', 'RULE_009')
        
        # RULE_011: Massive Upcoding (General procedures > 50,000)
        if random.random() < FRAUD_RATES['RULE_011_MASSIVE_UPCODING']:
            procedure = random.choice(procedures['general'])
            claim_amount = random.randint(50001, 150000)
            fraud_tracker['RULE_011'] += 1
            _mark_fraud(claim_id, 'massive_upcoding', 'RULE_011')
        
        # RULE_012: Blacklisted Hospital (HOSP_999)
        if random.random() < FRAUD_RATES['RULE_012_BLACKLISTED_HOSPITAL']:
            hospital_id = "HOSP_999"
            fraud_tracker['RULE_012'] += 1
            _mark_fraud(claim_id, 'blacklisted_hospital', 'RULE_012')
        
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
    
    # RULE_021: dedicated procedure-mill injection. Configurable; the default is
    # one (hospital, procedure, month) group of 60 claims, above
    # pmjay.procedure_mill_threshold (50). A fixed month keeps the group stable.
    mill_procedure = procedures['surgery'][0]
    mill_admission = '2024-06-15'
    for g in range(MILL_GROUPS):
        hospital_id = f"HOSP_MILL_{g:02d}"
        for k in range(MILL_GROUP_SIZE):
            claim_id = f"CLM_MILL_{g:02d}_{k:03d}"
            claims.append({
                'ClaimID': claim_id,
                'BeneficiaryID': random.choice(ben_ids),
                'HospitalID': hospital_id,
                'AdmissionDate': mill_admission,
                'DischargeDate': '2024-06-18',
                'ProcedureName': mill_procedure,
                'ClaimAmount': random.randint(30000, 100000),
                'PatientStatus': 'Discharged',
            })
            fraud_tracker['RULE_021'] += 1
            _mark_fraud(claim_id, 'procedure_mill', 'RULE_021')

    # --- P2c: cross-scheme PM-JAY events (Rule 025) --------------------------
    for cs in CROSS_SCHEME:
        if "PM-JAY Medical" not in cs['combo']:
            continue
        claim_id = f"CLM_CS_{cs['ben_id']}"
        admission_date = fake.date_between(start_date='-1y', end_date='today')
        claims.append({
            'ClaimID': claim_id,
            'BeneficiaryID': cs['ben_id'],
            'HospitalID': f"HOSP_{random.randint(1, 50):03d}",
            'AdmissionDate': admission_date,
            'DischargeDate': admission_date - timedelta(days=3),  # Rule 009
            'ProcedureName': random.choice(procedures['surgery']),
            'ClaimAmount': random.randint(30000, 100000),
            'PatientStatus': 'Discharged',
        })
        _mark_fraud(claim_id, 'cross_scheme', 'RULE_025')

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
# GROUND-TRUTH LABELS (data/labels.csv)
# =============================================================================

def _label_row(record_id, domain):
    """Build one labels row from the recorded injections for ``record_id``."""
    rid = str(record_id)
    injections = INJECTIONS.get(rid)
    if injections:
        fraud_types = sorted({fraud_type for fraud_type, _ in injections})
        rule_ids = sorted({rule_id for _, rule_id in injections})
        return [rid, domain, 1, "|".join(fraud_types), "|".join(rule_ids), split_for(rid)]
    if rid in HARD_NEGATIVES:
        return [rid, domain, 0, HARD_NEGATIVES[rid], None, split_for(rid)]
    return [rid, domain, 0, "", None, split_for(rid)]


def write_labels(df_beneficiaries, df_mgnrega, df_pmjay):
    """Write data/labels.csv: exactly one row per scannable record."""
    rows = []
    rows.extend(
        _label_row(rid, 'Civil Registry')
        for rid in df_beneficiaries['BeneficiaryID']
    )
    rows.extend(
        _label_row(rid, 'MGNREGA Labor')
        for rid in df_mgnrega['TransactionID']
    )
    rows.extend(
        _label_row(rid, 'PM-JAY Medical')
        for rid in df_pmjay['ClaimID']
    )
    labels = pd.DataFrame(rows, columns=LABEL_COLUMNS)
    labels.to_csv('data/labels.csv', index=False)

    hard_negatives = int((labels['fraud_type'] == 'hard_negative_blank_mobile').sum())
    print(
        f"   ✅ labels.csv created ({len(labels)} records, "
        f"{int(labels['is_fraud'].sum())} fraud, {hard_negatives} hard negatives)"
    )
    return labels


# =============================================================================
# MINIMUM EVENTS PER FRAUD TYPE (module P2c)
# =============================================================================

# Single-record fraud types the floor can top up: fraud_type -> (domain, rule).
# Structural rules (mega family / cartel / mill / cross-scheme) are floored by
# their own builders, so they are never thin and are not listed here.
_TYPE_RULE = {
    'invalid_mobile': ('civil', 'RULE_001'),
    'underage_jobcard': ('civil', 'RULE_002'),
    'suspicious_age': ('civil', 'RULE_003'),
    'mobile_sharing': ('civil', 'RULE_013'),
    'impossible_human': ('mgnrega', 'RULE_005'),
    'ghost_project': ('mgnrega', 'RULE_006'),
    'wage_theft': ('mgnrega', 'RULE_007'),
    'free_money': ('mgnrega', 'RULE_008'),
    'time_travel': ('pmjay', 'RULE_009'),
    'bio_mismatch': ('pmjay', 'RULE_010'),
    'massive_upcoding': ('pmjay', 'RULE_011'),
    'blacklisted_hospital': ('pmjay', 'RULE_012'),
}
# Structural / dedicated injections that are floored by their own builders.
_STRUCTURAL_TYPES = (
    'mega_family', 'muster_cartel', 'procedure_mill', 'cross_scheme',
)
# RULE_013 fires when a mobile is shared by more than max_mobile_sharing (3).
_SHARING_GROUP_SIZE = 5


def _as_date(value):
    """Return a ``date`` for either a date object or an ISO date string."""
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    return value


def _clean_indices(df, id_col):
    """Index labels of rows that have no injection and are not hard negatives."""
    injected = set(INJECTIONS) | set(HARD_NEGATIVES)
    return [i for i in df.index if str(df.at[i, id_col]) not in injected]


def _mutate_civil(df, fraud_type, picks, rng):
    dummy = get_config().civil_registry.dummy_mobile
    if fraud_type == 'invalid_mobile':
        for i in picks:
            df.at[i, 'MobileNumber'] = dummy
    elif fraud_type == 'underage_jobcard':
        for i in picks:
            df.at[i, 'Age'] = rng.randint(5, 17)
            if pd.isna(df.at[i, 'JobCardID']) or not str(df.at[i, 'JobCardID']):
                df.at[i, 'JobCardID'] = f"JC_TOPUP_{i:05d}"
    elif fraud_type == 'suspicious_age':
        for i in picks:
            df.at[i, 'Age'] = rng.randint(101, 150)
    elif fraud_type == 'mobile_sharing':
        for start in range(0, len(picks), _SHARING_GROUP_SIZE):
            shared = f"97{rng.randint(10000000, 99999999)}"
            for i in picks[start:start + _SHARING_GROUP_SIZE]:
                df.at[i, 'MobileNumber'] = shared


def _mutate_mgnrega(df, fraud_type, picks, rng):
    if fraud_type == 'impossible_human':
        for i in picks:
            days = rng.randint(16, 30)
            df.at[i, 'DaysWorked'] = days
            df.at[i, 'TotalAmount'] = days * int(df.at[i, 'WageRate'])
    elif fraud_type == 'ghost_project':
        for i in picks:
            df.at[i, 'WorkCode'] = f"WC_{rng.randint(100, 999)}_000"
    elif fraud_type == 'wage_theft':
        for i in picks:
            expected = int(df.at[i, 'DaysWorked']) * int(df.at[i, 'WageRate'])
            df.at[i, 'TotalAmount'] = expected + rng.choice(
                [-2000, -1000, 1000, 2000, 5000]
            )
    elif fraud_type == 'free_money':
        for i in picks:
            df.at[i, 'DaysWorked'] = 0
            df.at[i, 'TotalAmount'] = rng.randint(1000, 5000)


def _mutate_pmjay(df, df_ben, fraud_type, picks, rng):
    if fraud_type == 'time_travel':
        for i in picks:
            admission = _as_date(df.at[i, 'AdmissionDate'])
            df.at[i, 'DischargeDate'] = admission - timedelta(days=3)
    elif fraud_type == 'blacklisted_hospital':
        hospital = get_config().pmjay.blacklisted_hospital
        for i in picks:
            df.at[i, 'HospitalID'] = hospital
    elif fraud_type == 'massive_upcoding':
        procedure = get_config().pmjay.general_procedures[0]
        for i in picks:
            df.at[i, 'ProcedureName'] = procedure
            df.at[i, 'ClaimAmount'] = rng.randint(50001, 150000)
    elif fraud_type == 'bio_mismatch':
        procedure = get_config().pmjay.female_only_procedures[0]
        males = df_ben.loc[df_ben['Gender'] == 'M', 'BeneficiaryID'].tolist()
        for i in picks:
            df.at[i, 'BeneficiaryID'] = rng.choice(males)
            df.at[i, 'ProcedureName'] = procedure


def apply_min_events_floor(df_ben, df_mgn, df_pmjay, min_events):
    """Raise every thin fraud type to ``min_events`` within the prevalence cap.

    Rows are *mutated* in place (never added), so the scannable-record count -
    and therefore the cap - is unchanged. A type is left alone if it has too few
    clean rows or if the raise would push total fraud above
    ``1.5 x prevalence x scannable``. Returns ``(frames..., report)``.
    """
    rng = make_rng(get_config().seed + 300)
    report: dict[str, str] = {}
    total_fraud = len(INJECTIONS)

    def cap() -> float:
        scannable = len(df_ben) + len(df_mgn) + len(df_pmjay)
        return 1.5 * SIM.prevalence * scannable

    thin = sorted(
        (t for t in _TYPE_RULE if INJECTION_COUNTS[t] < min_events),
        key=lambda t: (INJECTION_COUNTS[t], t),
    )
    for fraud_type in thin:
        count = INJECTION_COUNTS[fraud_type]
        domain, rule_id = _TYPE_RULE[fraud_type]
        add = min_events - count
        if domain == 'civil':
            if fraud_type == 'mobile_sharing':
                add = math.ceil(add / _SHARING_GROUP_SIZE) * _SHARING_GROUP_SIZE
            pool, mutate, args = (
                _clean_indices(df_ben, 'BeneficiaryID'), _mutate_civil, (df_ben,)
            )
        elif domain == 'mgnrega':
            pool, mutate, args = (
                _clean_indices(df_mgn, 'TransactionID'), _mutate_mgnrega, (df_mgn,)
            )
        else:
            pool, mutate, args = (
                _clean_indices(df_pmjay, 'ClaimID'), _mutate_pmjay, (df_pmjay, df_ben)
            )

        if len(pool) < add:
            report[fraud_type] = (
                f"NOT raised ({count}): only {len(pool)} clean {domain} rows"
            )
            continue
        if total_fraud + add > cap():
            report[fraud_type] = (
                f"NOT raised ({count}): would push total fraud to {total_fraud + add}"
                f" > 1.5x prevalence cap ({cap():.0f})"
            )
            continue

        picks = rng.sample(pool, add)
        mutate(*args, fraud_type, picks, rng)
        for i in picks:
            if domain == 'civil':
                record_id = df_ben.at[i, 'BeneficiaryID']
            elif domain == 'mgnrega':
                record_id = df_mgn.at[i, 'TransactionID']
            else:
                record_id = df_pmjay.at[i, 'ClaimID']
            _mark_fraud(record_id, fraud_type, rule_id)
        total_fraud += add
        report[fraud_type] = f"raised {count} -> {count + add}"

    return df_ben, df_mgn, df_pmjay, report


def print_injection_table(min_events: int) -> None:
    """Print the actual injected record counts per fraud_type."""
    print("\n" + "=" * 78)
    print("in-sample injection counts, not generalization")
    print("-" * 78)
    print(f"   {'fraud_type':34s} {'events':>7s}   status")
    all_types = sorted(
        set(INJECTION_COUNTS) | set(_TYPE_RULE) | set(_STRUCTURAL_TYPES)
        | {'hard_negative_blank_mobile'}
    )
    for fraud_type in all_types:
        n = INJECTION_COUNTS[fraud_type]
        if fraud_type == 'hard_negative_blank_mobile':
            status = "hard negative (not fraud)"
        elif n >= min_events:
            status = "ok"
        else:
            status = "not evaluable (< min_events_per_type)"
        print(f"   {fraud_type:34s} {n:7d}   {status}")
    print("-" * 78)
    print(f"   {'TOTAL injected records':34s} {sum(INJECTION_COUNTS.values()):7d}")


def print_floor_report(report: dict[str, str]) -> None:
    """Print the outcome of the min-events-per-type floor."""
    print("\n" + "-" * 78)
    print("MIN EVENTS PER TYPE FLOOR (cap = 1.5 x prevalence x scannable)")
    print("-" * 78)
    if not report:
        print("   no thin fraud types; floor not needed")
        return
    for fraud_type in sorted(report):
        print(f"   {fraud_type:34s} {report[fraud_type]}")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    # Generate all datasets
    df_ben = generate_beneficiaries()
    df_mgn = generate_mgnrega_transactions(df_ben)
    df_pmjay = generate_pmjay_transactions(df_ben)

    # P2c: raise thin fraud types to the configured floor (within the cap).
    min_events = get_config().simulator.min_events_per_type
    df_ben, df_mgn, df_pmjay, floor_report = apply_min_events_floor(
        df_ben, df_mgn, df_pmjay, min_events
    )
    # Persist the post-floor tables so the floor rows reach the scanner.
    df_ben.to_csv('data/beneficiaries.csv', index=False)
    df_mgn.to_csv('data/transactions_mgnrega.csv', index=False)
    df_pmjay.to_csv('data/transactions_pmjay.csv', index=False)

    # Ground-truth labels (one row per scannable record) and injection table.
    write_labels(df_ben, df_mgn, df_pmjay)
    print_injection_table(min_events)
    print_floor_report(floor_report)

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
    print(f"   - data/labels.csv")
    print(f"   - output/reports/fraud_ground_truth.json")
    print(f"\n🔍 Next step: Run audit_scanner.py to detect the injected fraud!")
    print("="*70)