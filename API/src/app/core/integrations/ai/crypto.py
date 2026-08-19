"""AES-GCM/AAD wrapper for BYOK provider-key ciphertext.

Distinct from ``core/integrations/crypto.py`` (Fernet, no AAD, reused
across every ``integrations`` row's OAuth tokens) because:

  * Fernet has no additional-authenticated-data slot — an insider
    with SQL write could copy row A's ciphertext into row B's
    ``encrypted_key`` column and cause org B's traffic to be billed
    against org A's OpenAI account. AAD binds each ciphertext to
    ``(org_id, key_id, key_version)``; a copy fails to decrypt.

  * Sharing a single encryption key across every secret class means
    one env-var leak decrypts every secret in the app. The dedicated
    KEK env var (``AI_PROVIDER_KEY_KEK``) is rotated independently
    of ``INTEGRATIONS_ENCRYPTION_KEY`` / ``FERNET_KEY`` /
    ``JWT_SECRET_KEY``.

The tests/test_ai_provider_kek_isolation.py pin-test refuses the app
to boot if any two of those env vars are equal — the boot-time
signal that the operator set the KEK correctly.

Usage:

    from src.app.core.integrations.ai.crypto import encrypt, decrypt
    ct, nonce = encrypt(b"sk-abc123", aad=b"org:key:v1")
    pt = decrypt(ct, nonce, aad=b"org:key:v1")   # → b"sk-abc123"
    decrypt(ct, nonce, aad=b"other")             # → raises AADMismatchError
"""

from __future__ import annotations

import base64
import binascii
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import AI_PROVIDER_KEY_KEK


class AADMismatchError(Exception):
    """Raised when AES-GCM decryption fails — either the ciphertext
    was tampered with OR the AAD supplied at decrypt time does not
    match the AAD that was used at encrypt time. Callers should treat
    this as "the key is unusable — refuse to serve any request that
    would use it" and surface a generic error to the operator (the
    exception carries no ciphertext or plaintext)."""


def _decode_kek(raw: str) -> bytes:
    """The KEK is stored as a url-safe-base64 32-byte string.
    Decoded here at import time — fails fast if malformed."""
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _build_aesgcm() -> AESGCM:
    if not AI_PROVIDER_KEY_KEK:
        raise RuntimeError(
            "AI_PROVIDER_KEY_KEK is not set. Generate one with: "
            "python -c 'import secrets, base64; "
            "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())' "
            "and add it to secrets.enc.env via `run secrets-edit`."
        )
    try:
        raw = _decode_kek(AI_PROVIDER_KEY_KEK)
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError(
            "AI_PROVIDER_KEY_KEK is not valid base64-url-safe."
        ) from exc
    if len(raw) != 32:
        raise RuntimeError(
            f"AI_PROVIDER_KEY_KEK must decode to 32 bytes, got {len(raw)}. "
            "Regenerate with: python -c 'import secrets, base64; "
            "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'"
        )
    return AESGCM(raw)


def _get_aesgcm() -> AESGCM:
    """Lazy build — the app can boot without ``AI_PROVIDER_KEY_KEK``;
    only the moment an org tries to store a key does the KEK become
    required. This mirrors ``PROPERTY_LINK_ENCRYPTION_KEY`` in the
    same file."""
    return _build_aesgcm()


def encrypt(plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """Encrypt ``plaintext`` with a fresh 12-byte nonce, binding the
    ciphertext to ``aad``. Returns ``(ciphertext, nonce)``. Callers
    store both columns in ``tbl_ai_provider_keys``."""
    if not isinstance(plaintext, bytes) or not isinstance(aad, bytes):
        raise TypeError("plaintext and aad must be bytes")
    nonce = secrets.token_bytes(12)
    ct = _get_aesgcm().encrypt(nonce, plaintext, aad)
    return ct, nonce


def decrypt(ciphertext: bytes, nonce: bytes, aad: bytes) -> bytes:
    """Decrypt. Raises :class:`AADMismatchError` on tamper OR
    AAD mismatch. Never surfaces the underlying ``InvalidTag`` —
    the caller doesn't need to distinguish tamper from mismatch
    (both mean "this row is unusable")."""
    if not isinstance(ciphertext, bytes) or not isinstance(nonce, bytes):
        raise TypeError("ciphertext and nonce must be bytes")
    if not isinstance(aad, bytes):
        raise TypeError("aad must be bytes")
    try:
        return _get_aesgcm().decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise AADMismatchError(
            "ciphertext failed to decrypt — either tampered with or "
            "AAD does not match the encrypt-time AAD"
        ) from exc


def build_aad(org_id: str, key_id: str, key_version: int) -> bytes:
    """Standard AAD shape used across every row. Callers must not
    build the AAD ad-hoc — every mismatch is a decrypt failure, and
    a single stray formatting difference (missing colon, hex vs
    dashes on the UUID) would render every ciphertext undecodable."""
    return f"{org_id}:{key_id}:{key_version}".encode()


__all__ = [
    "AADMismatchError",
    "build_aad",
    "decrypt",
    "encrypt",
]
