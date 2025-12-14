import pandas as pd
import random
from faker import Faker
from datetime import datetime, timedelta
import uuid

# Initialize Faker for Indian context
fake = Faker('en_IN')
Faker.seed(42)  # For reproducibility

# --- CONFIGURATION ---
NUM_BENEFICIARIES = 2000
NUM_MGNREGA_TXNS = 5000
NUM_PMJAY_TXNS = 3000

# Fraud Ratios (5% of data will be "poisoned")
FRAUD_RATIO = 0.05 

print("🚀 Starting Data Generation for 'Ghotala Pradesh'...")

# ==========================================
# 1. GENERATE BENEFICIARIES (The People)
# ==========================================
print(f"   -> Generating {NUM_BENEFICIARIES} Beneficiaries...")

beneficiaries = []
family_ids = [fake.uuid4() for _ in range(int(NUM_BENEFICIARIES / 4))] # Pool of families

for i in range(NUM_BENEFICIARIES):
    # FRAUD PATTERN 1: "The Mob of 999" (Identity Fraud)
    # 5% of users share the exact same dummy mobile number
    if random.random() < FRAUD_RATIO:
        mobile = "9999999999"
    else:
        mobile = fake.phone_number()

    # FRAUD PATTERN 2: "The Infinite Family" (Ration Card Fraud)
    # Occasionally assign a massive number of people to one Family ID
    if i < 50: # First 50 people belong to ONE family (Suspicious)
        family_id = family_ids[0] 
    else:
        family_id = random.choice(family_ids)

    ben = {
        'BeneficiaryID': f"BEN_{10000+i}",
        'Name': fake.name(),
        'Age': random.randint(1, 90),
        'Gender': random.choice(['M', 'F', 'O']),
        'MobileNumber': mobile,
        'AadhaarHash':  uuid.uuid4().hex[:12].upper(), # Simulated Hash
        'FamilyID': family_id,
        'District': 'Ghotala Pradesh',
        'JobCardID': f"JC_{random.randint(1000, 9999)}" if random.random() > 0.3 else None, # 70% have Job Cards
        'Is_Deceased': False # Track status for Lazarus fraud
    }
    
    # Mark some as deceased for future fraud
    if random.random() < 0.02:
        ben['Is_Deceased'] = True
        
    beneficiaries.append(ben)

df_ben = pd.DataFrame(beneficiaries)
df_ben.to_csv('data/beneficiaries.csv', index=False)
print("   ✅ beneficiaries.csv created.")


# ==========================================
# 2. GENERATE MGNREGA TRANSACTIONS (Work)
# ==========================================
print(f"   -> Generating {NUM_MGNREGA_TXNS} MGNREGA Transactions...")

mgnrega_txns = []
valid_job_cards = df_ben[df_ben['JobCardID'].notnull()]['JobCardID'].tolist()

for i in range(NUM_MGNREGA_TXNS):
    job_card = random.choice(valid_job_cards)
    start_date = fake.date_between(start_date='-1y', end_date='today')
    
    # Standard values
    days_worked = random.randint(5, 14) # Standard is max 14 per muster
    wage_per_day = 230 # Approx standard rate
    
    # FRAUD PATTERN 3: "The Impossible Human" (Labor Fraud)
    # Worker claims to work > 15 days in a single 15-day muster roll
    is_fraud = False
    if random.random() < FRAUD_RATIO:
        days_worked = random.randint(20, 30) # IMPOSSIBLE
        is_fraud = True
        
    total_wage = days_worked * wage_per_day
    
    # FRAUD PATTERN 4: "Material-Labor Violation" (Project Level)
    # Just flagging high material cost work codes
    work_code = f"WC_{random.randint(100, 500)}"
    
    txn = {
        'TransactionID': f"TXN_MGN_{i}",
        'JobCardID': job_card,
        'WorkCode': work_code,
        'MusterRollID': f"MR_{random.randint(10000, 99999)}",
        'WorkStartDate': start_date,
        'DaysWorked': days_worked,
        'WageRate': wage_per_day,
        'TotalAmount': total_wage,
        'Audit_Tag': "Fraud" if is_fraud else "Normal" # Hidden label for testing
    }
    mgnrega_txns.append(txn)

df_mgn = pd.DataFrame(mgnrega_txns)
df_mgn.to_csv('data/transactions_mgnrega.csv', index=False)
print("   ✅ transactions_mgnrega.csv created.")


# ==========================================
# 3. GENERATE PM-JAY TRANSACTIONS (Health)
# ==========================================
print(f"   -> Generating {NUM_PMJAY_TXNS} PM-JAY Claims...")

pmjay_txns = []
# Filter only people with PMJAY IDs (Assuming all beneficiaries are eligible for simplicity)
ben_ids = df_ben['BeneficiaryID'].tolist()

for i in range(NUM_PMJAY_TXNS):
    ben_id = random.choice(ben_ids)
    ben_record = df_ben[df_ben['BeneficiaryID'] == ben_id].iloc[0]
    
    admission_date = fake.date_between(start_date='-1y', end_date='today')
    discharge_date = admission_date + timedelta(days=random.randint(2, 10))
    claim_amount = random.randint(5000, 50000)
    
    # FRAUD PATTERN 5: "Time Travel" (Data Anomaly)
    # Discharge date is BEFORE Admission date
    if random.random() < FRAUD_RATIO:
        discharge_date = admission_date - timedelta(days=random.randint(1, 5))
        
    # FRAUD PATTERN 6: "The Lazarus Effect" (Ghost Patient)
    # A deceased person claims treatment
    if ben_record['Is_Deceased']:
        # This is automatically fraud because they are dead
        pass 
        
    # FRAUD PATTERN 7: "Upcoding" (High Cost for Minor Issue)
    procedure = random.choice(['Cataract', 'Hysterectomy', 'Dialysis', 'General Ward', 'Fracture'])
    if procedure == 'General Ward' and random.random() < FRAUD_RATIO:
        claim_amount = 150000 # Suspiciously high for General Ward

    txn = {
        'ClaimID': f"CLM_{i}",
        'BeneficiaryID': ben_id,
        'HospitalID': f"HOSP_{random.randint(1, 20)}",
        'AdmissionDate': admission_date,
        'DischargeDate': discharge_date,
        'ProcedureName': procedure,
        'ClaimAmount': claim_amount,
        'PatientStatus': 'Discharged'
    }
    pmjay_txns.append(txn)

df_pmjay = pd.DataFrame(pmjay_txns)
df_pmjay.to_csv('data/transactions_pmjay.csv', index=False)
print("   ✅ transactions_pmjay.csv created.")

print("\n🎉 Phase 1 Complete. Data is ready for your Agents.")