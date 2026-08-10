"""
Bank Detail Encryption at Rest using AES-128 (Fernet) + HMAC-SHA256.

Ensures vendor bank routing & account numbers are stored ENCRYPTED in PostgreSQL
and transparently decrypted when retrieved by authorized application logic.
"""
import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy.types import String, TypeDecorator

ENCRYPTION_KEY_RAW = os.getenv(
    "BANK_DETAILS_ENCRYPTION_KEY",
    "uO_8s7m3YVpX7J2xK9wL0qR1tU3vW5zY7aB9cD1eF3g=",
)


def _get_fernet_instance() -> Fernet:
    """Initialize Fernet cipher using 32-byte url-safe base64 master key."""
    raw_key_bytes = ENCRYPTION_KEY_RAW.encode("utf-8")
    hashed = hashlib.sha256(raw_key_bytes).digest()
    key_b64 = base64.urlsafe_b64encode(hashed)
    return Fernet(key_b64)


_cipher = _get_fernet_instance()


def encrypt_bank_detail(plain_text: Optional[str]) -> Optional[str]:
    """Encrypt plain bank detail string (routing/account) to Fernet ciphertext."""
    if not plain_text:
        return plain_text
    if plain_text.startswith("gAAAAA"):
        return plain_text  # Already encrypted
    encrypted_bytes = _cipher.encrypt(plain_text.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_bank_detail(cipher_text: Optional[str]) -> Optional[str]:
    """Decrypt Fernet ciphertext back to plain bank detail string."""
    if not cipher_text:
        return cipher_text
    if not cipher_text.startswith("gAAAAA"):
        return cipher_text  # Unencrypted fallback
    try:
        decrypted_bytes = _cipher.decrypt(cipher_text.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception:
        return cipher_text


class EncryptedBankDetailType(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for Encrypted Bank Details at Rest.

    Automatically encrypts value when binding to SQL parameters and
    decrypts when loading column from database result sets.
    """
    impl = String(255)
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        if value is not None:
            return encrypt_bank_detail(value)
        return value

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        if value is not None:
            return decrypt_bank_detail(value)
        return value
