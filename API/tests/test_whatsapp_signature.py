"""HMAC-SHA256 signature verification on the WhatsApp webhook.

Meta signs the raw body with the app secret. We must verify exactly
that — using the raw bytes, not a re-serialised JSON copy. These
tests pin down the contract.
"""

from __future__ import annotations

import hashlib
import hmac

from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter

SECRET = "test-app-secret"


def _adapter() -> WhatsAppAdapter:
    return WhatsAppAdapter(phone_id="x", token="x", app_secret=SECRET, verify_token="x")


def _sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verifies_correct_signature():
    body = b'{"hello":"world"}'
    assert _adapter().verify_signature(body, _sign(body)) is True


def test_rejects_wrong_signature():
    body = b'{"hello":"world"}'
    assert _adapter().verify_signature(body, "sha256=deadbeef") is False


def test_rejects_missing_header():
    assert _adapter().verify_signature(b"body", None) is False


def test_rejects_unprefixed_header():
    body = b"x"
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    # Missing "sha256=" prefix — must be rejected even though the hex is correct.
    assert _adapter().verify_signature(body, digest) is False


def test_rejects_signature_for_different_body():
    body = b'{"a":1}'
    other = b'{"a":2}'
    assert _adapter().verify_signature(body, _sign(other)) is False


def test_verify_subscription_handshake():
    a = _adapter()
    assert a.verify_subscription("subscribe", "x") is True
    assert a.verify_subscription("subscribe", "wrong") is False
    assert a.verify_subscription("unsubscribe", "x") is False
    assert a.verify_subscription(None, None) is False
