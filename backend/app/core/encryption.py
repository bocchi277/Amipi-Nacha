"""
Bank Detail Encryption at Rest (Fernet / AES-128-CBC + HMAC-SHA256).

Vendor routing and account numbers are stored encrypted in PostgreSQL and decrypted
transparently by the ORM.

Key handling
------------
The encryption key previously had a hardcoded fallback committed to this file, so
anybody with read access to the repository could decrypt every vendor's bank details
out of a database dump. ``BANK_DETAILS_ENCRYPTION_KEY`` is now **required**.

Rotation is supported through ``BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS`` (comma
separated). Values are encrypted with the primary key and decrypted with the primary
*or* any fallback, which is what makes a rotation possible at all: without it, changing
the key makes every existing row permanently unreadable. The procedure is:

1. Set ``BANK_DETAILS_ENCRYPTION_KEY`` to the new key and put the OLD key in
   ``BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS``. The app can now read old rows and writes
   new ones with the new key.
2. Run ``python scripts/rotate_encryption_key.py`` to rewrite every stored value with
   the new key.
3. Remove the old key from the fallback list.

Deployments migrating off the old built-in default must pass that default as a
fallback for step 1; it is available as ``LEGACY_INSECURE_DEFAULT_KEY`` below.
"""
import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.types import String, TypeDecorator

logger = logging.getLogger(__name__)

# The key that used to be hardcoded here. Retained ONLY so existing deployments can
# list it as a fallback while re-encrypting. Never use it as a primary key.
LEGACY_INSECURE_DEFAULT_KEY = "uO_8s7m3YVpX7J2xK9wL0qR1tU3vW5zY7aB9cD1eF3g="

# Fernet ciphertext always begins with this once base64-encoded.
_FERNET_PREFIX = "gAAAAA"

_ENV_PRIMARY = "BANK_DETAILS_ENCRYPTION_KEY"
_ENV_FALLBACKS = "BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS"
_ENV_ALLOW_INSECURE = "AMIPI_ALLOW_INSECURE_ENCRYPTION_KEY"


def _derive_fernet_key(raw: str) -> bytes:
    """
    Derive a Fernet key from an arbitrary passphrase.

    SHA-256 of the passphrase, base64url-encoded. Kept identical to the original
    derivation so data encrypted before this change stays readable.
    """
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _load_keys() -> tuple[str, list[str]]:
    primary = (os.getenv(_ENV_PRIMARY) or "").strip()
    fallbacks = [
        k.strip()
        for k in (os.getenv(_ENV_FALLBACKS) or "").split(",")
        if k.strip()
    ]

    if not primary:
        # Local development and the test suite may opt in to the legacy key rather
        # than inventing one, but a real deployment must not start without a key.
        if os.getenv(_ENV_ALLOW_INSECURE) == "1":
            logger.warning(
                "%s is not set; falling back to the INSECURE legacy key because %s=1. "
                "Never do this in production: the key is published in source control.",
                _ENV_PRIMARY, _ENV_ALLOW_INSECURE,
            )
            primary = LEGACY_INSECURE_DEFAULT_KEY
        else:
            raise RuntimeError(
                f"\n"
                f"==================================================================\n"
                f" {_ENV_PRIMARY} IS NOT SET\n"
                f"==================================================================\n"
                f" Vendor bank details are encrypted at rest with this key. It has no\n"
                f" default any more, because the previous default was committed to\n"
                f" source control and could decrypt any database dump.\n"
                f"\n"
                f" Generate one:\n"
                f"   python -c \"import secrets; print(secrets.token_urlsafe(48))\"\n"
                f"\n"
                f" If this deployment already holds data encrypted with the old\n"
                f" built-in default, set the new key AND list the old one:\n"
                f"   {_ENV_FALLBACKS}=\"{LEGACY_INSECURE_DEFAULT_KEY}\"\n"
                f" then run scripts/rotate_encryption_key.py\n"
                f"\n"
                f" For local development only:\n"
                f"   {_ENV_ALLOW_INSECURE}=1\n"
                f"==================================================================\n"
            )

    if primary == LEGACY_INSECURE_DEFAULT_KEY and os.getenv(_ENV_ALLOW_INSECURE) != "1":
        raise RuntimeError(
            f"{_ENV_PRIMARY} is set to the published legacy default key, which offers "
            f"no protection. Generate a new key and move the legacy value into "
            f"{_ENV_FALLBACKS} so existing rows remain readable while you re-encrypt."
        )

    return primary, fallbacks


def _build_cipher() -> MultiFernet:
    primary, fallbacks = _load_keys()
    keys = [Fernet(_derive_fernet_key(primary))]
    keys.extend(Fernet(_derive_fernet_key(k)) for k in fallbacks)
    if fallbacks:
        logger.info(
            "Bank detail encryption initialised with 1 primary key and %d decrypt-only "
            "fallback key(s). Run scripts/rotate_encryption_key.py then remove the "
            "fallbacks.", len(fallbacks),
        )
    return MultiFernet(keys)


_cipher: Optional[MultiFernet] = None


def get_cipher() -> MultiFernet:
    """Lazily build the cipher so an unset key fails at first use, not at import."""
    global _cipher
    if _cipher is None:
        _cipher = _build_cipher()
    return _cipher


def reset_cipher_cache() -> None:
    """Force the cipher to be rebuilt. Used by the rotation script and by tests."""
    global _cipher
    _cipher = None


def encrypt_bank_detail(plain_text: Optional[str]) -> Optional[str]:
    """Encrypt a bank detail with the PRIMARY key."""
    if not plain_text:
        return plain_text
    if plain_text.startswith(_FERNET_PREFIX):
        return plain_text  # Already encrypted
    return get_cipher().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_bank_detail(cipher_text: Optional[str]) -> Optional[str]:
    """
    Decrypt a bank detail using the primary key or any configured fallback.

    A value that fails to decrypt is returned unchanged rather than raising, matching
    the previous behaviour so a single unreadable row cannot take down a whole listing.
    The failure is logged, because it means either the key is wrong or the row was
    written with a key no longer configured.
    """
    if not cipher_text:
        return cipher_text
    if not cipher_text.startswith(_FERNET_PREFIX):
        return cipher_text  # Legacy plaintext row
    try:
        return get_cipher().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error(
            "Failed to decrypt a bank detail: no configured key can read it. Add the "
            "key it was written with to %s.", _ENV_FALLBACKS,
        )
        return cipher_text
    except Exception:
        logger.exception("Unexpected error decrypting a bank detail")
        return cipher_text


class EncryptedBankDetailType(TypeDecorator):
    """
    SQLAlchemy type that encrypts on write and decrypts on read.

    NOTE for query authors: Fernet is non-deterministic, so the same input encrypts to
    a different ciphertext every time. ``WHERE account_number = :value`` can therefore
    never match. Compare decrypted values in Python instead.
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
