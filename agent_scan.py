import pandas as pd
import google.generativeai as genai
import json
import time
import os
from dotenv import load_dotenv # Requires: pip install python-dotenv

# --- 1. CONFIGURATION & SECURITY ---
# Load environment variables from the .env file
load_dotenv()

# Fetch the key securely
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError("❌ No API Key found! Please check your .env file.")

# Configure Gemini with REST transport (better for corporate/uni networks)
genai.configure(api_key=API_KEY, transport='rest')

# --- 2. LOAD DATA ---
print("📂 Loading Data...")
# CRITICAL FIX: Force MobileNumber to be a string to match '9999999999'
df_ben = pd.read_csv('beneficiaries.csv', dtype={'MobileNumber': str})
print(f"   -> Loaded {len(df_ben)} beneficiaries.")

# --- 3. DEFINE THE TOOLS (The "Hands") ---
def check_beneficiary_database(mobile_number: str):
    """
    Queries the database to count how many families are linked to a mobile number.
    Use this to detect 'Mob of 999' or Identity Cartels.
    """
    # Look up the real data from our CSV
    matches = df_ben[df_ben['MobileNumber'] == mobile_number]
    linked_count = len(matches)
    unique_families = matches['FamilyID'].nunique()
    
    risk = "LOW"
    if linked_count > 10:
        risk = "CRITICAL_FRAUD"
    elif linked_count > 3:
        risk = "HIGH"
        
    return {
        "mobile": mobile_number,
        "linked_beneficiaries": int(linked_count),
        "unique_families": int(unique_families),
        "risk_verdict": risk
    }

# Register the tool
tools_list = [check_beneficiary_database]

# --- 4. INITIALIZE THE AGENT (The "Brain") ---
# Using the newer model version you have access to
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash', 
    tools=tools_list,
    system_instruction="""
    You are the 'Principal Auditor' for the Government of India.
    Your job is to screen beneficiaries for Identity Fraud.
    
    RULES:
    1. If you see a Mobile Number, ALWAYS use the `check_beneficiary_database` tool to audit it.
    2. Analyze the tool's output:
       - If risk is 'CRITICAL_FRAUD' (more than 10 links), verify it as a 'Section 420 Violation'.
       - If risk is 'LOW', verify it as 'Clean'.
    3. Output your final verdict in a short JSON format.
    """
)

# --- 5. THE SCANNING LOOP (With Retry Logic) ---
print("\n🚀 Starting Automated Audit Scan...")

# Create a mixed sample to ensure we see both Fraud and Clean results
fraud_sample = df_ben[df_ben['MobileNumber'] == '9999999999'].head(2)
# Pick 3 random normal people (who are NOT the fraudsters)
normal_sample = df_ben[df_ben['MobileNumber'] != '9999999999'].head(3)
audit_batch = pd.concat([fraud_sample, normal_sample])

results = []
chat = model.start_chat(enable_automatic_function_calling=True)

for index, row in audit_batch.iterrows():
    print(f"\n--- 🔍 Auditing Beneficiary: {row['Name']} ({row['MobileNumber']}) ---")
    prompt = f"Audit this beneficiary: Name: {row['Name']}, Mobile: {row['MobileNumber']}"
    
    # Retry Loop for Error 429 (Rate Limit)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = chat.send_message(prompt)
            verdict = response.text.strip()
            print(f"🤖 Agent Verdict: {verdict}")
            
            results.append({
                "ID": row['BeneficiaryID'],
                "Mobile": row['MobileNumber'],
                "Agent_Report": verdict
            })
            
            # Success! Brief pause to be polite to the API
            time.sleep(2) 
            break 
            
        except Exception as e:
            if "429" in str(e):
                wait_time = 20 # Wait 20 seconds if we hit the limit
                print(f"   ⚠️ Rate Limit Hit. Cooling down for {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"❌ Error: {e}")
                break

# --- 6. SAVE REPORT ---
with open("fraud_report.json", "w") as f:
    json.dump(results, f, indent=2)

print("\n✅ Audit Complete. Report saved to 'fraud_report.json'.")