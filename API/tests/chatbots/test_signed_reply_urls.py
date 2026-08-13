"""Signed-reply-URL tests — pure Python.

Covers the sign/verify/pack/unpack primitives + HTML renders. Full
DB-bound tests (nonce persist, atomic consume race, POST records
inbound + publishes event, GET is prefetch-safe) live in
``test_signed_reply_urls_db.py`` — deferred to batch pytest per
memory ``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

import pytest

from src.app.core.chatbots.signed_reply_urls import (
    _b64url_decode,
    _b64url_encode,
    _pack_signature,
    _sign,
    _unpack_signature,
    render_error_page,
    render_interstitial,
    render_success_page,
)


# --- Base64url round-trip ---------------------------------------------------


def test_b64url_round_trip() -> None:
    for _ in range(20):
        raw = secrets.token_bytes(32)
        encoded = _b64url_encode(raw)
        assert "=" not in encoded  # padding stripped
        assert "/" not in encoded and "+" not in encoded  # URL-safe alphabet
        assert _b64url_decode(encoded) == raw


def test_b64url_short_input() -> None:
    for length in (1, 2, 3, 4, 5, 16, 24, 32):
        raw = secrets.token_bytes(length)
        assert _b64url_decode(_b64url_encode(raw)) == raw


# --- HMAC signing ---------------------------------------------------------


def test_hmac_sign_matches_stdlib() -> None:
    key = b"a" * 32
    payload = b"nonce.1234567890"
    theirs = _sign(payload, key)
    ours = base64.urlsafe_b64encode(
        hmac.new(key, payload, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    assert theirs == ours


def test_hmac_wrong_key_produces_different_signature() -> None:
    payload = b"nonce.1234567890"
    a = _sign(payload, b"a" * 32)
    b = _sign(payload, b"b" * 32)
    assert a != b


def test_hmac_wrong_payload_produces_different_signature() -> None:
    key = b"k" * 32
    a = _sign(b"nonce.1", key)
    b = _sign(b"nonce.2", key)
    assert a != b


# --- Pack / unpack --------------------------------------------------------


def test_pack_unpack_round_trip() -> None:
    signed = _pack_signature("mynonce", 1234567890, "sig_value")
    assert _unpack_signature(signed) == ("mynonce", 1234567890, "sig_value")


def test_unpack_rejects_wrong_shape() -> None:
    assert _unpack_signature("only.two") is None
    assert _unpack_signature("one_part") is None
    assert _unpack_signature("four.parts.here.now") is None
    assert _unpack_signature("nonce.not-int.sig") is None


# --- Interstitial HTML renderer ------------------------------------------


def test_interstitial_shows_button_label_and_org() -> None:
    html = render_interstitial(
        signature="a.b.c",
        button_label="I'm interested",
        org_name="Acme Corp",
    )
    assert "I&#x27;m interested" in html  # HTML-escaped
    assert "Acme Corp" in html
    assert 'form method="POST"' in html
    assert 'action="/r/a.b.c"' in html


def test_interstitial_escapes_xss_in_button_label() -> None:
    html = render_interstitial(
        signature="sig",
        button_label='<script>alert(1)</script>',
        org_name="Test",
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_interstitial_escapes_xss_in_org_name() -> None:
    html = render_interstitial(
        signature="sig",
        button_label="ok",
        org_name='"><img src=x onerror=alert(1)>',
    )
    assert 'onerror=alert' not in html
    assert "&lt;img" in html or "&quot;" in html


def test_interstitial_has_noindex_meta() -> None:
    """Search engines shouldn't index reply-URL pages."""
    html = render_interstitial(signature="s", button_label="ok", org_name="Test")
    assert 'name="robots" content="noindex,nofollow"' in html


def test_error_page_reveals_nothing() -> None:
    """Same shape for expired / consumed / forged — no info leak."""
    html_default = render_error_page()
    html_used = render_error_page("Already used")
    # The title differs but the body message is identical + generic.
    assert "no longer valid" in html_default
    assert "no longer valid" in html_used
    # No conversation contents / button labels / org names leaked.
    assert "conversation" not in html_default.lower()
    assert "run_id" not in html_default


def test_success_page_shows_reply_confirmation() -> None:
    html = render_success_page(button_label="Yes please", org_name="Acme")
    assert "Yes please" in html
    assert "Acme" in html
    assert "on its way" in html


# --- Router registration --------------------------------------------------


def test_reply_router_mounted_at_root() -> None:
    """Router prefix must be ``/r`` (not ``/api/v1/...``) so email
    URLs stay short + mail-client link scanners don't strip a
    versioned API path."""
    from src.app.core.chatbots.reply_router import router

    assert router.prefix == "/r"


def test_reply_router_exposes_get_and_post() -> None:
    from src.app.core.chatbots.reply_router import router

    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            methods_by_path.setdefault(route.path, set()).update(route.methods)

    assert "/r/{signature}" in methods_by_path
    assert "GET" in methods_by_path["/r/{signature}"]
    assert "POST" in methods_by_path["/r/{signature}"]


# --- Constant-time HMAC compare guardrail --------------------------------


def test_hmac_compare_digest_used() -> None:
    """Code-review guardrail — any refactor that switches to `==`
    for signature comparison is a timing-oracle vuln."""
    import inspect

    from src.app.core.chatbots import signed_reply_urls

    src = inspect.getsource(signed_reply_urls.verify)
    assert "compare_digest" in src, (
        "signed_reply_urls.verify must use hmac.compare_digest — do not "
        "switch to '==' comparison (timing oracle)"
    )
