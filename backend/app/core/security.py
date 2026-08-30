"""
Security Utilities: Password Hashing (PBKDF2-HMAC-SHA256) & JWT Tokens.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from typing import Any, Optional
import jwt

from app.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
# Bearer tokens are held in the browser's sessionStorage, so any script running on the
# page can read them. That is mitigated by escaping every rendered database value and by
# the response CSP, but a stolen token is usable until it expires and there is no
# server-side revocation for a stateless JWT.
#
# 24 hours was a long window for a system that moves money. 8 hours covers a working day,
# so an operator signs in once per shift, while cutting the useful life of a leaked token
# by two thirds. `get_current_user` re-reads the user on every request, so deactivating an
# account still takes effect immediately regardless of token lifetime.
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a 16-byte random salt."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}:{key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against PBKDF2-HMAC-SHA256 stored hash."""
    try:
        salt_hex, key_hex = hashed_password.split(":")
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        derived_key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
        return hmac_compare(derived_key, expected_key)
    except Exception:
        return False


def hmac_compare(val1: bytes, val2: bytes) -> bool:
    """Constant-time byte string comparison to prevent timing attacks."""
    return hmac.compare_digest(val1, val2)


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create signed JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None
