import os
import sys
from openai import OpenAI

api_key = os.environ.get('DEEPSEEK_API_KEY')
if not api_key:
    print("ERROR: DEEPSEEK_API_KEY env var not set")
    sys.exit(1)

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)

print(f"Testing DeepSeek API... (key length={len(api_key)}, prefix={api_key[:3]}-)")

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
    max_tokens=50
)

print("Response:", resp.choices[0].message.content)
print("Tokens used:")
print(f"  prompt: {resp.usage.prompt_tokens}")
print(f"  completion: {resp.usage.completion_tokens}")
print(f"  total: {resp.usage.total_tokens}")
print(f"Model used: {resp.model}")
print("OK")
