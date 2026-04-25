from __future__ import annotations

import json
import os
import bcrypt
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from jwt.api_jwt import decode as jwt_decode, encode as jwt_encode
from jwt.exceptions import PyJWTError as JWTError

AUTH_SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("AUTH_TOKEN_EXPIRE_MINUTES", "1440"))

USERS_FILE = Path(__file__).parent / "data" / "users.json"
USERS_FILE.parent.mkdir(exist_ok=True, mode=0o755)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {"users": [], "_meta": {"version": 1}}
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def _save_users(users_data: dict):
    users_data["_meta"]["last_modified"] = datetime.utcnow().isoformat()
    with open(USERS_FILE, "w") as f:
        json.dump(users_data, f, indent=2)


def get_user(username: str) -> dict | None:
    users = _load_users()
    for user in users["users"]:
        if user["username"] == username:
            return user
    return None


def create_user(username: str, password: str, email: str, is_admin: bool = False) -> dict:
    users = _load_users()
    if any(u["username"] == username for u in users["users"]):
        return None
    user_data = {
        "username": username,
        "password_hash": _hash_password(password),
        "email": email,
        "created_at": datetime.utcnow().isoformat(),
        "is_admin": is_admin,
        "is_approved": is_admin
    }
    users["users"].append(user_data)
    _save_users(users)
    return user_data


def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user:
        return False
    if not _verify_password(password, user["password_hash"]):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    encoded_jwt = jwt_encode(to_encode, key=AUTH_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt_decode(token, AUTH_SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user


def get_all_users() -> list:
    """Return all users."""
    users = _load_users()
    return users.get("users", [])


def approve_user(username: str) -> bool:
    """Approve a pending user."""
    users = _load_users()
    for user in users["users"]:
        if user["username"] == username:
            user["is_approved"] = True
            _save_users(users)
            return True
    return False


def delete_user(username: str) -> bool:
    """Delete a user."""
    users = _load_users()
    original_count = len(users["users"])
    users["users"] = [u for u in users["users"] if u["username"] != username]
    if len(users["users"]) < original_count:
        _save_users(users)
        return True
    return False