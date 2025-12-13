import google.generativeai as genai

genai.configure(api_key="AIzaSyAqI7GSZnfrABT4qSjpMbbqjLt345qiXvM") 

# List available models to prove connection
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f"✅ Connection Success! Found model: {m.name}")
        break