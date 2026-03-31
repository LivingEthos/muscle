#!/usr/bin/env python3
"""
SCLE API Test Script

Run this from your terminal where the MiniMax API is accessible.
Usage: python3 test_api.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("MINIMAX_API_BASE", "io")

from tools.scle.m27_client import M27Client, ANTHROPIC_BASE_URL_COM, ANTHROPIC_BASE_URL_IO

print("=" * 60)
print("SCLE API Test (Global Platform)")
print("=" * 60)

api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
if not api_key:
    print("\nERROR: No API key found!")
    print("Set ANTHROPIC_API_KEY or MINIMAX_API_KEY environment variable")
    print("\nExample:")
    print("  export ANTHROPIC_API_KEY='your-key'")
    sys.exit(1)

print(f"\nAPI Key: {api_key[:20]}...{api_key[-10:]}")
print(f"\nAvailable endpoints:")
print(f"  .com: {ANTHROPIC_BASE_URL_COM}")
print(f"  .io:  {ANTHROPIC_BASE_URL_IO}")
print(f"\n  ✓ Correct global endpoint is: api.minimax.io (not api.minimaxi.io)")

client = M27Client()
print(f"\nUsing endpoint: {client.base_url}")
print(f"Model: {client.model}")

print("\nTesting API connection...")
try:
    response, usage = client.chat(
        messages=[{"role": "user", "content": "Say 'Hello from SCLE!' in exactly 5 words"}],
        max_tokens=50
    )
    print(f"\n✓ SUCCESS!")
    print(f"  Response: {response}")
    print(f"  Tokens used: {usage.total} (in: {usage.input_tokens}, out: {usage.output_tokens})")
except Exception as e:
    print(f"\n✗ FAILED: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("Testing complete - SCLE is ready!")
print("=" * 60)
