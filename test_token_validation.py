#!/usr/bin/env python3
"""Test JWT token generation and validation."""

import sys
import os

project_root = Path('/Users/rstemmler/Documents/Drive/My_Documents/Python_ML_AI_Courses_2018/zotero-rag/zotero-rag')
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from auth import create_access_token, get_user, authenticate_user
from dotenv import load_dotenv
import asyncio
from fastapi.testclient import TestClient

from webapp import app

print("=" * 60)
print("TOKEN VALIDATION TEST")
print("=" * 60)

# Create a test client
client = TestClient(app)

# Test login
print("\n1. Testing login with admin credentials...")
response = client.post(
    "/api/login",
    data={
        "username": "admin",
        "password": "admin"
    }
)

if response.status_code == 200:
    data = response.json()
    token = data.get('access_token')
    print(f"✓ Login successful")
    print(f"  Token: {token[:50]}...")
    print(f"  Username: {data.get('username')}")
    print(f"  Is admin: {data.get('is_admin')}")
else:
    print(f"✗ Login failed: {response.status_code}")
    print(f"  Response: {response.text}")
    sys.exit(1)

# Test chat endpoint with token
print("\n2. Testing /api/chat endpoint with valid token...")
response = client.post(
    "/api/chat",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    },
    json={
        "message": "test",
        "conversation": [],
        "filters": {},
        "top_k": 1
    }
)

if response.status_code == 200:
    print(f"✓ Chat endpoint works with token")
    print(f"  Response accepted (SSE)")
else:
    print(f"⚠️  Chat endpoint returned: {response.status_code}")
    print(f"  Response: {response.text[:200]}")

# Test chat endpoint without token
print("\n3. Testing /api/chat endpoint without token...")
response = client.post(
    "/api/chat",
    headers={
        "Content-Type": "application/json"
    },
    json={
        "message": "test",
        "conversation": [],
        "filters": {},
        "top_k": 1
    }
)

if response.status_code == 401:
    print(f"✓ Chat correctly rejected without token")
else:
    print(f"⚠️  Unexpected response without token: {response.status_code}")
    print(f"  Response: {response.text}")

# Test filters endpoint with token
print("\n4. Testing /api/filters endpoint with valid token...")
response = client.get(
    "/api/filters",
    headers={
        "Authorization": f"Bearer {token}"
    }
)

if response.status_code == 200:
    print(f"✓ Filters endpoint works with token")
else:
    print(f"⚠️  Unexpected response: {response.status_code}")
    print(f"  Response: {response.text}")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
print("\nNote: The chat response may be empty due to no indexed data.")
print("But authentication should work correctly.")