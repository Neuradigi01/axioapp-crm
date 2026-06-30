"""Step 6 — HMAC verification + signature path tests for /events.

Tests the standalone ``_verify_inbound_signature`` helper directly so
we exercise the exact same HMAC algorithm the sidecar uses (Step 1's
``auth.ts``) without spinning up a TestClient / DB fixture.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from src.app.core.integrations.whatsapp_web.router import (
    _verify_inbound_signature,
)


_SECRET = "b" * 64


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return (
        "sha256="
        + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    )


def test_valid_signature_accepted(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.core.integrations.whatsapp_web.router."
        "WHATSAPP_WEB_INBOUND_HMAC_SECRET",
        _SECRET,
    )
    body = json.dumps({"type": "qr.updated"}).encode()
    assert _verify_inbound_signature(body, _sign(body)) is True


def test_tampered_signature_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.core.integrations.whatsapp_web.router."
        "WHATSAPP_WEB_INBOUND_HMAC_SECRET",
        _SECRET,
    )
    body = json.dumps({"type": "qr.updated"}).encode()
    sig = _sign(body)
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert _verify_inbound_signature(body, tampered) is False


def test_missing_header_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.core.integrations.whatsapp_web.router."
        "WHATSAPP_WEB_INBOUND_HMAC_SECRET",
        _SECRET,
    )
    body = b'{"type":"qr.updated"}'
    assert _verify_inbound_signature(body, None) is False
    assert _verify_inbound_signature(body, "") is False


def test_wrong_prefix_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.core.integrations.whatsapp_web.router."
        "WHATSAPP_WEB_INBOUND_HMAC_SECRET",
        _SECRET,
    )
    body = b'{"type":"qr.updated"}'
    sig = _sign(body).replace("sha256=", "sha1=")
    assert _verify_inbound_signature(body, sig) is False


def test_empty_secret_rejects_all(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.core.integrations.whatsapp_web.router."
        "WHATSAPP_WEB_INBOUND_HMAC_SECRET",
        "",
    )
    body = b'{"type":"qr.updated"}'
    assert _verify_inbound_signature(body, _sign(body)) is False


def test_different_secret_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.core.integrations.whatsapp_web.router."
        "WHATSAPP_WEB_INBOUND_HMAC_SECRET",
        _SECRET,
    )
    body = b'{"type":"qr.updated"}'
    sig = _sign(body, "c" * 64)
    assert _verify_inbound_signature(body, sig) is False
