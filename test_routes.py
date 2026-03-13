#!/usr/bin/env python3
"""Quick test to verify the route is working."""

from pathlib import Path
import sys

# Test the route decorators
with open("webapp.py", "r") as f:
    content = f.read()

# Check if the routes exist
has_root = '@app.get("/")' in content
has_index = '@app.get("/index.html")' in content

print("=" * 60)
print("ROUTE VERIFICATION TEST")
print("=" * 60)
print(f"✓ Root route (@app.get('/')): {has_root}")
print(f"✓ Index route (@app.get('/index.html')): {has_index}")

if has_root and has_index:
    print("\n✅ All routes are properly configured!")
else:
    print("\n❌ Some routes are missing!")
    sys.exit(1)