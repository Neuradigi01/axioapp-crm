"""Tests for the SSRF-defence fetcher
(``tasks/ai-assistants`` Step 10; Attacker C1, Cases §9-11).

Pure-Python — no live network. ``safe_fetch``'s DNS resolution is
mocked via ``socket.getaddrinfo`` monkey-patching so we exercise the
IP-filter branches without hitting the real DNS.
"""

from __future__ import annotations

import pytest

from src.app.shared.http.safe_fetch import (
    UnsafeUrlError,
    _is_private_ip,
    _validate_url,
)


# --- _is_private_ip -------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",  # RFC1918
        "172.16.5.5",  # RFC1918
        "192.168.1.1",  # RFC1918
        "127.0.0.1",  # loopback
        "169.254.169.254",  # link-local (AWS IMDS)
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local (private)
        "not-an-ip",  # unparseable → refused
    ],
)
def test_is_private_ip_rejects(ip: str) -> None:
    assert _is_private_ip(ip) is True


@pytest.mark.parametrize(
    "ip",
    [
        "8.8.8.8",  # public
        "1.1.1.1",  # public
        "142.250.190.14",  # google.com
        "2606:4700:4700::1111",  # cloudflare public IPv6
    ],
)
def test_is_private_ip_accepts_public(ip: str) -> None:
    assert _is_private_ip(ip) is False


# --- URL validation -------------------------------------------------------


def test_validate_url_rejects_ftp() -> None:
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("ftp://example.com/foo")
    assert exc.value.reason == "bad_scheme"


def test_validate_url_rejects_file_scheme() -> None:
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("file:///etc/passwd")
    assert exc.value.reason == "bad_scheme"


def test_validate_url_rejects_missing_host() -> None:
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("http:///nohost")
    assert exc.value.reason == "no_host"


def test_validate_url_rejects_literal_private_ip() -> None:
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("http://127.0.0.1/whatever")
    assert exc.value.reason == "private_ip_rejected"


def test_validate_url_rejects_literal_rfc1918_ip() -> None:
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("http://192.168.1.5/admin")
    assert exc.value.reason == "private_ip_rejected"


def test_validate_url_rejects_aws_imds() -> None:
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("http://169.254.169.254/latest/meta-data")
    assert exc.value.reason == "private_ip_rejected"


def test_validate_url_rejects_dns_that_resolves_private(monkeypatch) -> None:
    """Hostname that DNS-resolves to a private IP still rejects — this
    is the ``badguy.com A 10.0.0.1`` case."""
    monkeypatch.setattr(
        "src.app.shared.http.safe_fetch._resolve_host",
        lambda host: ["10.0.0.5"] if host == "badguy.com" else [],
    )
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("http://badguy.com/malicious")
    assert exc.value.reason == "private_ip_rejected"


def test_validate_url_rejects_unresolvable_host(monkeypatch) -> None:
    """Never-resolves host is refused (a name that resolves later
    shouldn't be optimistically accepted)."""
    monkeypatch.setattr(
        "src.app.shared.http.safe_fetch._resolve_host",
        lambda host: [],
    )
    with pytest.raises(UnsafeUrlError) as exc:
        _validate_url("http://never.resolves.example/")
    assert exc.value.reason == "unresolvable_host"


def test_validate_url_accepts_https_with_public_dns(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.app.shared.http.safe_fetch._resolve_host",
        lambda host: ["8.8.8.8"],
    )
    # No exception on the happy path.
    _validate_url("https://api.example.com/v1/foo")
