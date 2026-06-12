"""Step 8 — email tracking tests.

Four groups, no real DB:

  1. `tokens.encode` / `tokens.decode` — happy roundtrip, tampered
     sig rejected, malformed token rejected, unknown kind rejected.
  2. `pixel.inject` — places the tag before `</body>`, appends at
     end when no body tag, wraps empty input.
  3. `link_rewriter.rewrite` — rewrites http(s), skips mailto/tel/
     data/anchors, idempotent on already-tracker URLs.
  4. `footer.build` + `footer.has_required_address` — assembles
     compliance footer, gates send-time validation.

Convention: pure-function tests where possible. The router's DB-
side recording is left to integration tests (Step 8.5 once we wire
the inbox UI); the helpers covered here are the unique logic.
"""
from __future__ import annotations

import os
import re
import uuid

import pytest

# Tokens module reads TRACKING_HMAC_KEY at first use; set it here
# before any encode/decode call.
os.environ.setdefault(
    "TRACKING_HMAC_KEY", "test-key-do-not-use-in-prod-32bytes"
)


# Import AFTER env is set (encode/decode lazy-load the key, so the
# import order doesn't actually matter, but this is the safe shape).
from src.app.core.email.tracking import (  # noqa: E402
    footer as footer_mod,
    link_rewriter as links_mod,
    pixel as pixel_mod,
    tokens as tokens_mod,
)


_TRACKING_BASE = "https://t.example.com"


# --- 1. tokens -----------------------------------------------------------


class TestTokens:
    def test_roundtrip(self):
        mid = uuid.uuid4()
        token = tokens_mod.encode(message_id=mid, kind="o")
        payload = tokens_mod.decode(token)
        assert payload is not None
        assert payload["message_id"] == mid
        assert payload["kind"] == "o"

    def test_each_kind(self):
        mid = uuid.uuid4()
        for kind in ("o", "c", "u"):
            token = tokens_mod.encode(message_id=mid, kind=kind)
            payload = tokens_mod.decode(token)
            assert payload is not None
            assert payload["kind"] == kind

    def test_tampered_signature_rejected(self):
        token = tokens_mod.encode(message_id=uuid.uuid4(), kind="o")
        # Flip the LAST char of the signature half.
        payload_b64, sig_b64 = token.rsplit(".", 1)
        flipped = sig_b64[:-1] + ("a" if sig_b64[-1] != "a" else "b")
        tampered = f"{payload_b64}.{flipped}"
        assert tokens_mod.decode(tampered) is None

    def test_tampered_payload_rejected(self):
        token = tokens_mod.encode(message_id=uuid.uuid4(), kind="o")
        payload_b64, sig_b64 = token.rsplit(".", 1)
        flipped = payload_b64[:-1] + (
            "A" if payload_b64[-1] != "A" else "B"
        )
        tampered = f"{flipped}.{sig_b64}"
        assert tokens_mod.decode(tampered) is None

    def test_malformed_token_rejected(self):
        assert tokens_mod.decode("") is None
        assert tokens_mod.decode("nodot") is None
        assert tokens_mod.decode(".") is None
        assert tokens_mod.decode("a.") is None
        assert tokens_mod.decode(".b") is None

    def test_unknown_kind_rejected_at_encode(self):
        with pytest.raises(ValueError):
            tokens_mod.encode(
                message_id=uuid.uuid4(), kind="x"  # type: ignore[arg-type]
            )


# --- 2. pixel injection --------------------------------------------------


class TestPixel:
    def test_inserts_before_body_close(self):
        html = "<html><body><p>Hi</p></body></html>"
        result = pixel_mod.inject(
            html, token="tok123", base_url=_TRACKING_BASE
        )
        # Pixel sits immediately before `</body>`.
        idx_pixel = result.index('src="https://t.example.com')
        idx_close = result.index("</body>")
        assert idx_pixel < idx_close
        assert "<p>Hi</p>" in result

    def test_appends_when_no_body_tag(self):
        html = "<p>Just a paragraph</p>"
        result = pixel_mod.inject(
            html, token="tok123", base_url=_TRACKING_BASE
        )
        assert result.startswith("<p>Just a paragraph</p>")
        assert result.endswith("/>")

    def test_case_insensitive_body_close(self):
        html = "<html><BODY>X</BODY></html>"
        result = pixel_mod.inject(
            html, token="tok123", base_url=_TRACKING_BASE
        )
        # Inserts before the close tag regardless of casing.
        idx_pixel = result.index('src="https://t.example.com')
        idx_close = result.upper().index("</BODY>")
        assert idx_pixel < idx_close

    def test_empty_body_wraps_pixel(self):
        result = pixel_mod.inject(
            "", token="tok123", base_url=_TRACKING_BASE
        )
        assert "<div>" in result
        assert 'src="https://t.example.com' in result

    def test_pixel_url_format(self):
        result = pixel_mod.inject(
            "<body></body>",
            token="abcDEF",
            base_url=_TRACKING_BASE,
        )
        assert (
            f'src="{_TRACKING_BASE}/api/v1/track/o/abcDEF"' in result
        )

    def test_strips_trailing_slash_in_base(self):
        result = pixel_mod.inject(
            "<body></body>",
            token="t",
            base_url=_TRACKING_BASE + "/",
        )
        # No double-slash in the resulting URL.
        assert "//api/v1/track" not in result


# --- 3. link rewriter ----------------------------------------------------


class TestLinkRewriter:
    def test_rewrites_https_link(self):
        html = '<a href="https://x.com">click</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert "https://x.com" not in re.findall(
            r'href="([^"]+)"', result
        )[0]
        assert (
            f"{_TRACKING_BASE}/api/v1/track/c/tok?u=" in result
        )

    def test_rewrites_http_link(self):
        html = '<a href="http://x.com/path?q=1">click</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert f"{_TRACKING_BASE}/api/v1/track/c/tok?u=" in result

    def test_skips_mailto(self):
        html = '<a href="mailto:a@b.com">mail me</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        # Unchanged.
        assert 'href="mailto:a@b.com"' in result
        assert "/api/v1/track/c/" not in result

    def test_skips_tel(self):
        html = '<a href="tel:+15555551212">call</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert 'href="tel:+15555551212"' in result

    def test_skips_anchor(self):
        html = '<a href="#section">to section</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert 'href="#section"' in result

    def test_skips_data_uri(self):
        html = '<a href="data:text/plain,abc">data</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert 'href="data:text/plain,abc"' in result

    def test_skips_javascript(self):
        html = '<a href="javascript:alert(1)">x</a>'
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert "javascript:alert(1)" in result
        assert "/api/v1/track/c/" not in result

    def test_idempotent_on_already_tracked(self):
        # Pre-rewritten URL — should NOT be wrapped a second time.
        html = (
            f'<a href="{_TRACKING_BASE}/api/v1/track/c/tok?u=foo">x</a>'
        )
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert result == html

    def test_preserves_other_attributes(self):
        html = (
            '<a href="https://x.com" class="cta" target="_blank">'
            "click</a>"
        )
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        assert 'class="cta"' in result
        assert 'target="_blank"' in result

    def test_multiple_links_all_rewritten(self):
        html = (
            '<a href="https://a.com">A</a>'
            '<a href="https://b.com">B</a>'
        )
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        # Two click URLs, no original https:// hosts.
        click_matches = re.findall(
            r"/api/v1/track/c/tok\?u=", result
        )
        assert len(click_matches) == 2
        assert "https://a.com" not in result
        assert "https://b.com" not in result

    def test_single_quoted_href(self):
        html = "<a href='https://x.com'>click</a>"
        result = links_mod.rewrite(
            html, token="tok", base_url=_TRACKING_BASE
        )
        # Single-quoted href still rewritten, quote preserved.
        assert "/api/v1/track/c/tok?u=" in result
        assert "https://x.com" not in result


# --- 4. footer -----------------------------------------------------------


class _SettingsStub:
    def __init__(
        self,
        *,
        address_line1=None,
        address_line2=None,
        city=None,
        state=None,
        postal_code=None,
        country=None,
    ):
        self.address_line1 = address_line1
        self.address_line2 = address_line2
        self.city = city
        self.state = state
        self.postal_code = postal_code
        self.country = country


class TestFooter:
    def test_has_required_address_true(self):
        s = _SettingsStub(address_line1="123 Main St", city="BLR")
        assert footer_mod.has_required_address(s) is True

    def test_has_required_address_false_for_none(self):
        assert footer_mod.has_required_address(None) is False

    def test_has_required_address_false_for_empty(self):
        s = _SettingsStub()
        assert footer_mod.has_required_address(s) is False

    def test_build_includes_company_and_address(self):
        s = _SettingsStub(
            address_line1="123 Main",
            city="Bangalore",
            country="India",
        )
        result = footer_mod.build(
            org_name="Acme CRM",
            org_settings=s,
            unsubscribe_url="https://t.example.com/u/tok",
        )
        assert "Acme CRM" in result
        assert "123 Main" in result
        assert "Bangalore" in result
        assert "India" in result
        assert "https://t.example.com/u/tok" in result
        assert "Unsubscribe" in result

    def test_build_escapes_html_in_name(self):
        result = footer_mod.build(
            org_name='<script>alert(1)</script>',
            org_settings=None,
            unsubscribe_url="https://t.example.com/u/tok",
        )
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_append_inserts_before_body_close(self):
        html = "<html><body><p>X</p></body></html>"
        result = footer_mod.append(html, footer_html="FOOTER")
        idx_footer = result.index("FOOTER")
        idx_close = result.index("</body>")
        assert idx_footer < idx_close
        assert "<p>X</p>" in result

    def test_append_no_body_tag(self):
        result = footer_mod.append("<p>X</p>", footer_html="FOOTER")
        assert result == "<p>X</p>FOOTER"
