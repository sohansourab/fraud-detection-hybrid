print("--- 1. Script Started ---")

import google.generativeai as genai
import os

print("--- 2. Libraries Imported ---")

# PASTE YOUR KEY HERE
API_KEY = "AIzaSyAqI7GSZnfrABT4qSjpMbbqjLt345qiXvM" 

try:
    # Force REST transport (Fixes hanging on some networks)
    genai.configure(api_key=API_KEY, transport='rest')
    
    print("--- 3. Connecting to Google... ---")
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("Say 'Hello Auditor'")
    
    print(f"--- 4. SUCCESS! Response received: {response.text} ---")

except Exception as e:
    print(f"--- ❌ ERROR: {e} ---")

print("--- 5. Script Finished ---")