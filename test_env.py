# test_env.py
"""Check if .env is loading correctly."""

import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GROQ_API_KEY")

if key is None:
    print("FAILED: GROQ_API_KEY is None")
    print("Check that .env file is in the project root folder")
    print(f"Looking in: {os.getcwd()}")
elif key.strip() == "":
    print("FAILED: GROQ_API_KEY is empty string")
elif not key.startswith("gsk_"):
    print(f"WARNING: Key does not start with gsk_ — got: {key[:10]}...")
else:
    print(f"SUCCESS: Key loaded — {key[:8]}...{key[-4:]}")
    print(f"Key length: {len(key)} characters")