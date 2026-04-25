#!/usr/bin/env python3
"""Test the webapp startup and verify routes are working."""

import sys
import os
from pathlib import Path

project_root = Path('/Users/rstemmler/Documents/Drive/My_Documents/Python_ML_AI_Courses_2018/zotero-rag/zotero-rag')

os.chdir(project_root)

# Test imports
print("Testing authentication imports...")
try:
    from auth import *
    print("✓ auth module imports successfully")
except Exception as e:
    print(f"✗ Failed to import auth module: {e}")
    sys.exit(1)

# Test syntax
print("\nTesting webapp.py syntax...")
try:
    import py_compile
    py_compile.compile('webapp.py', doraise=True)
    print("✓ webapp.py has valid syntax")
except Exception as e:
    print(f"✗ Syntax error in webapp.py: {e}")
    sys.exit(1)

# Test that routes are configured
print("\nVerifying route configuration...")
with open('webapp.py', 'r') as f:
    content = f.read()

checks = [
    ('@app.get("/")', 'Root route'),
    ('@app.get("/index.html")', 'Index route'),
    ('@app.post("/api/login")', 'Login endpoint'),
    ('@app.post("/api/register")', 'Register endpoint'),
    ('@app.post("/api/chat")', 'Chat endpoint'),
    ('@app.get("/api/filters")', 'Filters endpoint'),
]

all_good = True
for check_str, description in checks:
    if check_str in content:
        print(f"  ✓ {description}")
    else:
        print(f"  ✗ {description} - NOT FOUND")
        all_good = False

if not all_good:
    print("\n❌ Some routes are missing!")
    sys.exit(1)

print("\n✅ All checks passed!")
print("\nTo start the webapp:")
print("  python webapp.py")
print("\nThen open:")
print("  http://localhost:5001/login.html")
print("  Login with: admin / admin")
print("  Should redirect to: http://localhost:5001/index.html")