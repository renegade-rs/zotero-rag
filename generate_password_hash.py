#!/usr/bin/env python3
"""Generate a password hash for the admin account."""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

passwords = ["admin", "password", "zotero123", "TestPassword123!", "anotherpass456@"]
hashes = {}

for pwd in passwords:
    hashes[pwd] = pwd_context.hash(pwd)

print("Password Hashes:")
print("-" * 60)
for pwd, hash_var in hashes.items():
    print(f"Password: '{pwd}'")
    print(f"Hash:     {hash_var}")
    print("-" * 60)