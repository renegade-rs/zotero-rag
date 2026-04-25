#!/usr/bin/env python3
"""Test authentication system."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from auth import get_user, _verify_password, _hash_password, create_user, authenticate_user, create_access_token, _load_users, _save_users

def test_password_hash():
    """Test the default admin password hash."""
    print("Testing password hash...")

    users = _load_users()
    admin = users["users"][0]

    # Should work with a simple password
    test_passwords = [
        "admin",
        "password",
        "1234567890",
        "zotero123",
        "Zotero2024!"
    ]

    for pwd in test_passwords:
        if _verify_password(pwd, admin["password_hash"]):
            print(f"✓ Password '{pwd}' works!")
            return pwd
        else:
            print(f"✗ Password '{pwd}' failed")

    print("No matching password found!")
    print(f"Stored hash: {admin['password_hash']}")
    print(f"Password hint: Try 'admin' or 'password'")

def test_user_creation():
    """Test creating a new user."""
    print("\nTesting user creation...")

    test_users = [
        {"username": "testuser1", "email": "test1@example.com", "password": "TestPassword123!"},
        {"username": "testuser2", "email": "test2@example.com", "password": "AnotherPass456@"},
    ]

    for user_data in test_users:
        user = create_user(user_data["username"], user_data["password"], user_data["email"])
        if user:
            print(f"✓ Created user: {user_data['username']}")
            password_match = _verify_password(user_data["password"], user["password_hash"])
            print(f"  - Password hash matches: {password_match}")
            print(f"  - Email: {user['email']}")
            print(f"  - Is admin: {user.get('is_admin', False)}")
            print(f"  - Is approved: {user.get('is_approved', False)}")
            if not password_match:
                print(f"  ✗ ERROR: Password verification failed for {user_data['username']}")
        else:
            users = _load_users()
            if any(u["username"] == user_data["username"] for u in users["users"]):
                print(f"  User {user_data['username']} already exists (duplicate test passed)")
            else:
                print(f"✗ Failed to create user: {user_data['username']}")
                print(f"  Error: User was None but doesn't exist in database")

def test_admin_access():
    """Test admin user access."""
    print("\nTesting admin access...")

    admin = get_user("admin")
    if admin and admin.get("is_admin"):
        print("✓ Admin user found and is admin")
    else:
        print("✗ Admin user not found or not admin")

def test_token_creation():
    """Test JWT token creation."""
    print("\nTesting JWT token creation...")

    admin = get_user("admin")
    if admin:
        token = create_access_token(data={"sub": admin["username"]})
        print(f"✓ Created token for {admin['username']}")
        print(f"  Token length: {len(token)} characters")

def test_duplicate_user():
    """Test duplicate user creation."""
    print("\nTesting duplicate user creation...")

    existing = create_user("admin", "somepassword", "admin@test.com")
    if existing:
        print("✗ Should not have created duplicate user")
    else:
        print("✓ Correctly prevented duplicate user creation")

if __name__ == "__main__":
    print("=" * 60)
    print("AUTHENTICATION SYSTEM TEST")
    print("=" * 60)

    try:
        test_password_hash()
        test_user_creation()
        test_admin_access()
        test_token_creation()
        test_duplicate_user()

        print("\n" + "=" * 60)
        print("TESTS COMPLETE")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)