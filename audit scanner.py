import pandas as pd
import ollama
import json
import time
import os

# --- CONFIGURATION ---
MODEL_NAME = "llama3.2"  # Ensure you ran 'ollama run llama3.2'
INPUT_FILE = "data/beneficiaries.csv"
OUTPUT_FILE = "output/reports/fraud_report.json"
#check to ensure folders exist:
import os
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

# --- 1. SETUP ---
if not os.path.exists(INPUT_FILE):
    raise FileNotFoundError(f"❌ {INPUT_FILE} not found! Run generate_data.py first.")

# Force Mobile to be String to catch "9999999999" correctly
df_ben = pd.read_csv(INPUT_FILE, dtype={'MobileNumber': str})
print(f"📂 Loaded {len(df_ben)} beneficiaries into the Secure Lab.")

# --- 2. THE ROOT AGENT ---
def run_root_agent_scan(dataframe, batch_size=20):
    print(f"\n🚀 Root Agent: Starting Local Scan with {MODEL_NAME}...")
    all_verdicts = []
    
    # Process in chunks
    for i in range(0, len(dataframe), batch_size):
        batch = dataframe.iloc[i : i+batch_size]
        
        # Prepare the data packet for the AI
        batch_text = ""
        for _, row in batch.iterrows():
            batch_text += f"- ID: {row['BeneficiaryID']}, Mobile: {row['MobileNumber']}\n"
            
        # The System Prompt (The Brain)
        prompt = f"""
        You are the Root Fraud Detection Agent. Analyze these beneficiaries.
        
        FRAUD LOGIC:
        1. If MobileNumber is '9999999999' -> Verdict: "CRITICAL FRAUD"
        2. If MobileNumber is missing or 'nan' -> Verdict: "SUSPICIOUS"
        3. Otherwise -> Verdict: "CLEAN"

        OUTPUT INSTRUCTIONS:
        Return ONLY a JSON list of objects. Do not write any other text.
        Format: [{{"ID": "...", "Verdict": "..."}}]
        
        DATA TO SCAN:
        {batch_text}
        """

        try:
            # Call Ollama Locally
            response = ollama.chat(
                model=MODEL_NAME, 
                messages=[{'role': 'user', 'content': prompt}],
                format='json' # <--- This guarantees valid JSON!
            )
            
            # Parse the response
            content = response['message']['content']
            data = json.loads(content)
            
            # Handle edge case: sometimes models wrap results in a key like "result": [...]
            if isinstance(data, dict):
                # Flatten it if it's inside a dictionary key
                first_key = list(data.keys())[0]
                if isinstance(data[first_key], list):
                    data = data[first_key]
                else:
                    data = [data] # It was just one object

            all_verdicts.extend(data)
            print(f"   ✅ Batch {i//batch_size + 1}: Analyzed {len(data)} records")
            
        except Exception as e:
            print(f"   ⚠️ Error on batch {i}: {e}")

    return all_verdicts

# --- 3. EXECUTION ---
if __name__ == "__main__":
    results = run_root_agent_scan(df_ben, batch_size=20)
    
    # Save the Intelligence Report
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\n🏁 Scan Complete. Intelligence Report saved to '{OUTPUT_FILE}'.")
    print(f"   Total Audited: {len(results)}")
    print(f"   Fraudsters Found: {len([x for x in results if 'FRAUD' in x.get('Verdict', '').upper()])}")