"""
Quick check that the Anthropic API key is valid and has credit.
Usage: python scripts/check_anthropic.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

try:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "say hi"}]
    )
    print("OK — API key is valid and has credit.")
    print(f"Response: {response.content[0].text}")
except anthropic.AuthenticationError:
    print("FAIL — Invalid API key.")
except anthropic.BadRequestError as e:
    print(f"FAIL — {e}")
except Exception as e:
    print(f"FAIL — {type(e).__name__}: {e}")
