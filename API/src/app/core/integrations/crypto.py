"""Fernet wrapper for at-rest OAuth-token encryption.

Every `access_token` and `refresh_token` stored in the `integrations`
table is encrypted with this module's `encrypt()` before write and
decrypted with `decrypt()` immediately before being passed to the
provider's API client. The plaintext NEVER touches:

  - the database (`*_enc` columns are ciphertext)
  - any API response (`IntegrationRead` schema excludes the `*_enc` fields)
  - any audit log payload
  - any error message (we catch decrypt failures and log a generic
    error without including the ciphertext)

Key management:

  - The key is a Fernet key — 32 url-safe-base64-encoded bytes,
    generated once per environment via `Fernet.generate_key()` and
    stored in the `INTEGRATIONS_ENCRYPTION_KEY` env var.
  - Generate a fresh dev key with:
        docker exec template_api-api-1 python -c \
            "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  - Lose the key = lose every stored token; every org must reconnect.
    Keep a copy in your secrets manager.
  - Rotation: Fernet supports `MultiFernet([new_key, old_key])` —
    deferred to a future task. v1 ships single-key.

The module reads the key once at import time and fails loudly if it's
missing — the API container won't start, which is the right default
for a security-critical setting (better to refuse to boot than to
ship encryption you can't decrypt).
"""
from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config import INTEGRATIONS_ENCRYPTION_KEY


def _build_fernet() -> Fernet:
    key = INTEGRATIONS_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "INTEGRATIONS_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())' "
            "and put it in your .env. See .env.example."
        )
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "INTEGRATIONS_ENCRYPTION_KEY is not a valid Fernet key "
            "(must be 32 url-safe-base64-encoded bytes). "
            "Regenerate with: python -c 'from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())'"
        ) from exc


_fernet = _build_fernet()


def encrypt(plain: str) -> str:
    """Encrypt a plaintext token. Returns the Fernet ciphertext as a
    UTF-8 string (Fernet output is already url-safe-base64, so the
    string is safe to store in a TEXT column directly)."""
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(cipher: str) -> str:
    """Decrypt a Fernet ciphertext back to plaintext. Raises
    `InvalidToken` if the ciphertext is malformed, was encrypted under
    a different key, or has been tampered with (Fernet includes an
    HMAC).

    Callers should catch `InvalidToken` and treat it as "the token is
    unusable" — typically: set status='error' on the integration row
    and force the Owner to reconnect."""
    return _fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")


def encrypt_optional(plain: Optional[str]) -> Optional[str]:
    """Convenience for the common case where the token may be None
    (refresh_token isn't always returned by every provider on every
    grant). None passes through unchanged."""
    return encrypt(plain) if plain is not None else None


def decrypt_optional(cipher: Optional[str]) -> Optional[str]:
    """Convenience for the common case where the ciphertext column is
    NULL (disconnected integration, or never had a refresh token)."""
    return decrypt(cipher) if cipher is not None else None


__all__ = [
    "InvalidToken",
    "decrypt",
    "decrypt_optional",
    "encrypt",
    "encrypt_optional",
]
