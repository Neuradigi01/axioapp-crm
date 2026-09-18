"""Fernet-based public-link tokens for CatalogItem.

Encodes ``(item_id, org_id)`` as an opaque, URL-safe token so the
public share URL never exposes internal UUIDs. Fernet gives symmetric
AES-128-CBC + HMAC-SHA256 in one primitive — tamper detection is
intrinsic, and rotating the key invalidates every outstanding link.

The Fernet instance is **lazily built** on first use so a missing
``CATALOG_LINK_ENCRYPTION_KEY`` doesn't block application boot; only
the public-URL endpoints fail (with a clear ``not configured`` message)
until the key is set in ``secrets.enc.env`` via ``run secrets-edit``.

The key is intentionally independent from ``PROPERTY_LINK_ENCRYPTION_KEY``
so rotating one entity's share links never invalidates the other.
"""

from __future__ import annotations

import uuid

from cryptography.fernet import Fernet, InvalidToken

import config

_fernet: Fernet | None = None
_key_error: RuntimeError | None = None


def _get_fernet() -> Fernet:
    global _fernet, _key_error
    if _fernet is not None:
        return _fernet
    if _key_error is not None:
        raise _key_error
    key = config.CATALOG_LINK_ENCRYPTION_KEY
    if not key:
        _key_error = RuntimeError(
            "CATALOG_LINK_ENCRYPTION_KEY is not set. Generate with: "
            "docker exec crm-api-1 python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' "
            "and add to secrets.enc.env via `run secrets-edit`."
        )
        raise _key_error
    try:
        _fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        _key_error = RuntimeError(
            "CATALOG_LINK_ENCRYPTION_KEY is not a valid Fernet key "
            "(must be 32 url-safe-base64-encoded bytes)."
        )
        raise _key_error from exc
    return _fernet


def reset_cache() -> None:
    """Test helper. Clears the cached Fernet + any recorded key error
    so the next call to ``_get_fernet`` re-reads
    ``config.CATALOG_LINK_ENCRYPTION_KEY``."""
    global _fernet, _key_error
    _fernet = None
    _key_error = None


def encode_catalog_token(item_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Encrypt ``(item_id, org_id)`` into an opaque URL-safe string.

    Encoding is a Fernet ciphertext of ``"{item_id}|{org_id}"`` —
    HMAC-authenticated, so any single-character tamper breaks the
    decrypt with ``InvalidToken``."""
    payload = f"{item_id}|{org_id}".encode("utf-8")
    return _get_fernet().encrypt(payload).decode("utf-8")


def decode_catalog_token(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Decrypt and split a token into ``(item_id, org_id)``.

    Returns ``None`` on any failure — invalid Fernet token, wrong key,
    malformed payload. Callers translate ``None`` into a 404 without
    leaking which failure mode fired (no side channel on existence).
    """
    try:
        decrypted = _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        pid_str, oid_str = decrypted.split("|", 1)
        return uuid.UUID(pid_str), uuid.UUID(oid_str)
    except (InvalidToken, ValueError):
        return None


def encode_catalog_store_token(org_id: uuid.UUID) -> str:
    """Encrypt just ``org_id`` into an opaque URL-safe string.

    Used by the "share the whole storefront" flow — one link that
    opens the org's public grid of every published product. The
    ``store:`` prefix disambiguates from per-item tokens so a leaked
    or reused store token can never decode as an item token (the
    router-side decoder rejects the wrong prefix)."""
    payload = f"store:{org_id}".encode("utf-8")
    return _get_fernet().encrypt(payload).decode("utf-8")


def decode_catalog_store_token(token: str) -> uuid.UUID | None:
    """Decrypt a store token into ``org_id``. Returns ``None`` on any
    failure — invalid Fernet token, wrong key, malformed payload,
    or wrong prefix (i.e. someone tried to feed a per-item token
    to the store endpoint). Callers translate ``None`` into a 404."""
    try:
        decrypted = _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        prefix, _, oid_str = decrypted.partition(":")
        if prefix != "store":
            return None
        return uuid.UUID(oid_str)
    except (InvalidToken, ValueError):
        return None


__all__ = [
    "decode_catalog_store_token",
    "decode_catalog_token",
    "encode_catalog_store_token",
    "encode_catalog_token",
    "reset_cache",
]
