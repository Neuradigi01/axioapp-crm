"""whatsapp-platform-upgrade Step 26 — quick-links boundary tests.

Pure-Python coverage of:
  * Slug shape + entropy.
  * Prefilled-body hash normalisation (whitespace + case).
  * wa.me URL construction (urlencode on emoji / non-ASCII).
  * QR PNG / SVG bytes (magic-byte checks).
  * Public-endpoint rate limiter (sliding window).

DB-touching paths (CRUD insert / RLS isolation / attribution match
against a live conversation) are exercised by the smoke flow —
same precedent as prior steps.

Cases:
  1.  ``_new_slug`` returns 8 chars from base62.
  2.  ``_new_slug`` collides rarely — 1000 calls = 1000 distinct.
  3.  ``hash_prefilled`` is None on empty / None / whitespace only.
  4.  ``hash_prefilled`` is whitespace + case insensitive.
  5.  ``hash_prefilled`` returns 64-char hex.
  6.  ``build_wa_me_url`` urlencodes a basic message.
  7.  ``build_wa_me_url`` handles non-ASCII (Hindi).
  8.  ``build_wa_me_url`` strips non-digit characters from phone.
  9.  ``build_wa_me_url`` returns base URL when no message.
 10.  ``render_png`` produces a PNG magic-byte stream.
 11.  ``render_svg`` produces an SVG byte stream.
 12.  ``render_png`` accepts non-standard sizes (falls back to nearest).
 13.  ``_rate_limit_ok`` allows requests under the cap.
 14.  ``_rate_limit_ok`` rejects past the cap within the window.
 15.  ``_rate_limit_ok`` re-allows after the window expires (clock patch).
"""
from __future__ import annotations

import time

import pytest

from src.app.core.integrations.whatsapp.qr_generator import (
    render_png,
    render_svg,
)
from src.app.core.integrations.whatsapp.quick_links import (
    _new_slug,
    build_wa_me_url,
    hash_prefilled,
)
from src.app.core.integrations.whatsapp.quick_links_router import (
    _RATE_LIMIT_HITS,
    _rate_buckets,
    _rate_limit_ok,
)


class _StubLink:
    """Minimal stand-in for the WhatsAppQuickLink ORM row."""

    def __init__(
        self,
        *,
        phone_number: str = "919999988888",
        prefilled_message: str | None = None,
    ) -> None:
        self.phone_number = phone_number
        self.prefilled_message = prefilled_message


class TestSlug:
    def test_eight_char_base62(self):
        slug = _new_slug()
        assert len(slug) == 8
        for ch in slug:
            assert ch.isalnum()

    def test_low_collision(self):
        # 8-char base62 = 218 trillion combos; 1000 calls should never
        # collide. If this ever fails, our randomness source is broken.
        seen = {_new_slug() for _ in range(1000)}
        assert len(seen) == 1000


class TestHashPrefilled:
    def test_empty_inputs_yield_none(self):
        assert hash_prefilled(None) is None
        assert hash_prefilled("") is None
        assert hash_prefilled("   ") is None
        assert hash_prefilled("\t\n") is None

    def test_normalises_whitespace_and_case(self):
        a = hash_prefilled("Hello World")
        b = hash_prefilled("  hello   world  ")
        c = hash_prefilled("HELLO\tWORLD")
        assert a == b == c

    def test_returns_sha256_hex(self):
        h = hash_prefilled("anything")
        assert h is not None
        assert len(h) == 64
        int(h, 16)  # parses as hex


class TestBuildWaMeUrl:
    def test_basic_message(self):
        url = build_wa_me_url(
            _StubLink(prefilled_message="I saw your billboard")
        )
        assert url.startswith("https://wa.me/919999988888?text=")
        assert "I%20saw%20your%20billboard" in url

    def test_non_ascii_hindi(self):
        url = build_wa_me_url(
            _StubLink(prefilled_message="नमस्ते Sharma Furniture")
        )
        # The Devanagari characters get percent-encoded; the encoded
        # bytes start with `%E0%A4` for the नमस्ते prefix.
        assert "%E0%A4" in url

    def test_strips_phone_formatting(self):
        url = build_wa_me_url(
            _StubLink(
                phone_number="+91 99999-88888",
                prefilled_message="hi",
            )
        )
        assert url.startswith("https://wa.me/919999988888?")

    def test_no_message(self):
        url = build_wa_me_url(_StubLink(prefilled_message=None))
        assert url == "https://wa.me/919999988888"
        # Empty string also yields no querystring.
        url2 = build_wa_me_url(_StubLink(prefilled_message=""))
        assert url2 == "https://wa.me/919999988888"


class TestQrGenerator:
    def test_png_magic(self):
        blob = render_png("https://example.test/wa/abc123", size_px=512)
        assert isinstance(blob, bytes)
        # PNG signature: 8-byte magic.
        assert blob[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(blob) > 100

    def test_svg_payload(self):
        blob = render_svg("https://example.test/wa/abc123")
        assert isinstance(blob, bytes)
        # SVG payload contains the literal `<svg` start tag.
        assert b"<svg" in blob

    def test_nonstandard_size_falls_back(self):
        # 333 px isn't in the size map; render should still succeed.
        blob = render_png("https://example.test/wa/abc123", size_px=333)
        assert blob[:8] == b"\x89PNG\r\n\x1a\n"


class TestRateLimiter:
    def setup_method(self) -> None:
        _rate_buckets.clear()

    def teardown_method(self) -> None:
        _rate_buckets.clear()

    def test_allows_under_cap(self):
        ip = "1.2.3.4"
        for _ in range(_RATE_LIMIT_HITS):
            assert _rate_limit_ok(ip) is True

    def test_rejects_over_cap(self):
        ip = "1.2.3.5"
        for _ in range(_RATE_LIMIT_HITS):
            assert _rate_limit_ok(ip) is True
        assert _rate_limit_ok(ip) is False

    def test_resets_after_window(self, monkeypatch):
        ip = "1.2.3.6"
        for _ in range(_RATE_LIMIT_HITS):
            _rate_limit_ok(ip)
        assert _rate_limit_ok(ip) is False
        # Move clock past the 60-second window.
        original_time = time.time
        monkeypatch.setattr(
            "src.app.core.integrations.whatsapp.quick_links_router.time.time",
            lambda: original_time() + 120,
        )
        assert _rate_limit_ok(ip) is True

    def test_no_ip_always_ok(self):
        assert _rate_limit_ok(None) is True
        assert _rate_limit_ok("") is True
