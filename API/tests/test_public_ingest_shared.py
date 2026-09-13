"""Unit tests for the ``shared/`` helpers landed in Step 3 of
``tasks/custom-events/``.

The Redis-backed halves (sliding window admission, idempotency
reserve, nonce cache) are covered by the smoke suite that runs
against a live redis container — this file focuses on the pure-Python
edges: regex validation, HMAC constant-time compare, timestamp
window arithmetic, XFF chain walking, trusted-proxy parsing, and
the startup fail-loud check.

These tests intentionally do NOT touch the network or Redis so they
run inside pytest's default fixtures in seconds.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

import pytest

from src.app.shared.hmac_verify import (
    verify_signature,
)
from src.app.shared.http.client_ip import (
    parse_client_ip,
    parse_trusted_proxies,
)
from src.app.shared.idempotency import (
    InvalidIdempotencyKey,
    _validate_key,
)


# --- Idempotency-key regex --------------------------------------------------


class TestIdempotencyKeyRegex:
    def test_accepts_typical_uuid(self):
        _validate_key(str(uuid.uuid4()))

    def test_accepts_dot_colon_underscore_dash(self):
        _validate_key("run_42:step-3.attempt1")

    def test_rejects_empty(self):
        with pytest.raises(InvalidIdempotencyKey):
            _validate_key("")

    def test_rejects_overlong(self):
        with pytest.raises(InvalidIdempotencyKey):
            _validate_key("a" * 129)

    def test_rejects_whitespace(self):
        with pytest.raises(InvalidIdempotencyKey):
            _validate_key("has whitespace")

    def test_rejects_unicode(self):
        with pytest.raises(InvalidIdempotencyKey):
            _validate_key("café")

    def test_rejects_control_chars(self):
        with pytest.raises(InvalidIdempotencyKey):
            _validate_key("bad\nkey")

    def test_rejects_non_string(self):
        with pytest.raises(InvalidIdempotencyKey):
            _validate_key(None)  # type: ignore[arg-type]


# --- HMAC signature ---------------------------------------------------------


class TestHMACVerify:
    _SECRET = "super-secret-shhhh"
    _BODY = b'{"event":"test","payload":{"x":1}}'

    def _sig(self, body: bytes, ts: str | None = None) -> str:
        mac = hmac.new(self._SECRET.encode(), digestmod=hashlib.sha256)
        if ts is not None:
            mac.update(ts.encode())
            mac.update(b".")
        mac.update(body)
        return "sha256=" + mac.hexdigest()

    def test_ok_no_timestamp(self):
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=self._sig(self._BODY),
            secret=self._SECRET,
        )
        assert result.ok is True
        assert result.reason == "signature_ok"

    def test_ok_with_timestamp(self):
        ts = str(int(time.time()))
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=self._sig(self._BODY, ts),
            secret=self._SECRET,
            timestamp_header=ts,
        )
        assert result.ok is True

    def test_missing_secret(self):
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=self._sig(self._BODY),
            secret="",
        )
        assert result.ok is False
        assert result.reason == "missing_secret"

    def test_missing_header(self):
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=None,
            secret=self._SECRET,
        )
        assert result.ok is False
        assert result.reason == "missing_signature_header"

    def test_bad_signature(self):
        result = verify_signature(
            raw_body=self._BODY,
            signature_header="sha256=" + "0" * 64,
            secret=self._SECRET,
        )
        assert result.ok is False
        assert result.reason == "bad_signature"

    def test_signature_length_wrong_rejected(self):
        result = verify_signature(
            raw_body=self._BODY,
            signature_header="sha256=abc",
            secret=self._SECRET,
        )
        assert result.ok is False
        assert result.reason == "missing_signature_header"

    def test_timestamp_out_of_window_rejected(self):
        # Timestamp 1 hour in the past — well outside the 5 min window.
        ts = str(int(time.time()) - 3600)
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=self._sig(self._BODY, ts),
            secret=self._SECRET,
            timestamp_header=ts,
        )
        assert result.ok is False
        assert result.reason == "timestamp_out_of_window"

    def test_timestamp_future_within_skew_accepted(self):
        # 90s ahead — inside the default 150s clock-skew tolerance.
        ts = str(int(time.time()) + 90)
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=self._sig(self._BODY, ts),
            secret=self._SECRET,
            timestamp_header=ts,
        )
        assert result.ok is True

    def test_replay_with_different_timestamp_rejected(self):
        # An attacker captures (sig, ts0), then presents (sig, ts1).
        # Because the signature is bound to the timestamp, verify with a
        # fresh timestamp must fail.
        ts_old = str(int(time.time()))
        sig_old = self._sig(self._BODY, ts_old)
        ts_fresh = str(int(time.time()) + 30)
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=sig_old,
            secret=self._SECRET,
            timestamp_header=ts_fresh,
        )
        assert result.ok is False
        assert result.reason == "bad_signature"

    def test_accepts_raw_hex_without_prefix(self):
        raw = self._sig(self._BODY).split("=", 1)[1]
        result = verify_signature(
            raw_body=self._BODY,
            signature_header=raw,
            secret=self._SECRET,
        )
        assert result.ok is True


# --- XFF / trusted-proxy parsing --------------------------------------------


class _FakeRequest:
    def __init__(self, *, peer: str | None, xff: str | None = None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = {"x-forwarded-for": xff} if xff else {}


class TestTrustedProxyParsing:
    def test_empty_returns_empty_list(self):
        assert parse_trusted_proxies("") == []
        assert parse_trusted_proxies(None) == []

    def test_single_ip_widened_to_host_prefix(self):
        nets = parse_trusted_proxies("10.0.0.1")
        assert len(nets) == 1
        assert str(nets[0]) == "10.0.0.1/32"

    def test_cidr_range(self):
        nets = parse_trusted_proxies("10.0.0.0/24, 192.168.1.0/24")
        assert len(nets) == 2

    def test_ipv6(self):
        nets = parse_trusted_proxies("2001:db8::/32")
        assert len(nets) == 1

    def test_malformed_dropped_not_crashed(self):
        # A stray token should not blow up parsing — degrade to
        # dropping the bad entry so the caller can still function
        # with the good ones.
        nets = parse_trusted_proxies("10.0.0.1, not-a-cidr, 192.168.0.0/24")
        assert len(nets) == 2


class TestClientIpParsing:
    def test_returns_peer_when_no_trusted_proxies(self):
        req = _FakeRequest(peer="203.0.113.5", xff="8.8.8.8")
        assert parse_client_ip(req, []) == "203.0.113.5"

    def test_returns_peer_when_peer_not_trusted(self):
        # XFF is present but the transport-level peer is NOT in the
        # trusted list — we must NOT read XFF (would let a direct
        # caller forge their client IP).
        req = _FakeRequest(peer="99.99.99.99", xff="8.8.8.8")
        trusted = parse_trusted_proxies("10.0.0.0/8")
        assert parse_client_ip(req, trusted) == "99.99.99.99"

    def test_returns_xff_when_peer_is_trusted(self):
        # Reverse-proxy scenario: peer is the ingress in 10/8, XFF
        # carries the real caller.
        req = _FakeRequest(peer="10.0.0.5", xff="203.0.113.5")
        trusted = parse_trusted_proxies("10.0.0.0/8")
        assert parse_client_ip(req, trusted) == "203.0.113.5"

    def test_walks_xff_right_to_left(self):
        # Chain: real client, proxy1, proxy2 (both proxies trusted).
        # Peer is proxy2 (trusted), rightmost XFF is proxy1 (trusted),
        # next is the real client (not trusted). Correct answer:
        # the real client.
        req = _FakeRequest(
            peer="10.0.0.5",  # proxy2
            xff="203.0.113.5, 10.0.0.2",  # client, proxy1
        )
        trusted = parse_trusted_proxies("10.0.0.0/8")
        assert parse_client_ip(req, trusted) == "203.0.113.5"

    def test_ipv6_peer_matched_against_ipv6_range(self):
        req = _FakeRequest(peer="2001:db8::1", xff="203.0.113.5")
        trusted = parse_trusted_proxies("2001:db8::/32")
        assert parse_client_ip(req, trusted) == "203.0.113.5"

    def test_unknown_when_no_peer(self):
        req = _FakeRequest(peer=None)
        assert parse_client_ip(req, []) == "unknown"


# --- Startup checks ---------------------------------------------------------


class TestStartupChecks:
    def test_dev_permits_empty_trusted_proxies(self, monkeypatch):
        import src.app.shared.startup_checks as sc

        monkeypatch.setattr(sc, "IS_DEVELOPMENT", True)
        monkeypatch.setattr(sc, "TRUSTED_PROXIES", "")
        sc.check_trusted_proxies()  # should not raise

    def test_prod_rejects_empty_trusted_proxies(self, monkeypatch):
        import src.app.shared.startup_checks as sc

        monkeypatch.setattr(sc, "IS_DEVELOPMENT", False)
        monkeypatch.setattr(sc, "TRUSTED_PROXIES", "")
        with pytest.raises(sc.StartupCheckFailed):
            sc.check_trusted_proxies()

    def test_prod_accepts_populated_trusted_proxies(self, monkeypatch):
        import src.app.shared.startup_checks as sc

        monkeypatch.setattr(sc, "IS_DEVELOPMENT", False)
        monkeypatch.setattr(sc, "TRUSTED_PROXIES", "10.0.0.0/8")
        sc.check_trusted_proxies()  # should not raise

    def test_prod_rejects_all_malformed_trusted_proxies(self, monkeypatch):
        import src.app.shared.startup_checks as sc

        monkeypatch.setattr(sc, "IS_DEVELOPMENT", False)
        # All tokens malformed → parse_trusted_proxies returns [] →
        # same failure as empty.
        monkeypatch.setattr(sc, "TRUSTED_PROXIES", "not-a-cidr, also-bad")
        with pytest.raises(sc.StartupCheckFailed):
            sc.check_trusted_proxies()
