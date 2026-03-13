#!/usr/bin/env python3
"""Clean up test users and set up the system."""

import os
import sys
from pathlib import Path

# Clear and test again
for module in list(sys.modules.keys()):
    if 'auth' in module:
        del sys.modules[module]

os.chdir('/Users/rstemmler/Documents/Drive/My_Documents/Python_ML_AI_Courses_2018/zotero-rag/zotero-rag')

from auth import _save_users, _load_users

print("Cleaning up test users...")

users = _load_users()
original_count = len(users['users'])
original_users = users['users'].copy()

# Filter out test users
test_prefixes = ['testuser', 'finaltest', 'realtest', 'realtest']
users['users'] = [u for u in users['users'] if not any(u['username'].startswith(prefix) for prefix in test_prefixes)]

new_count = len(users['users'])
removed_count = original_count - new_count

if removed_count > 0:
    print(f"Removed {removed_count} test user(s)")
else:
    print("No test users found to remove")

_save_users(users)
print("Cleanup complete. Admin user preserved.")

# Show final user list
users = _load_users()
print(f"\nFinal user count: {len(users['users'])}")
for user in users['users']:
    print(f"  - {user['username']} (admin: {user.get('is_admin', False)}, approved: {user.get('is_approved', False)})")