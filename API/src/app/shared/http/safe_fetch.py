"""SSRF-defence HTTP fetcher
(``tasks/ai-assistants`` Step 10; Attacker review C1, Case §9).

The knowledge-source ``url`` type lets an operator paste an arbitrary
URL and asks our worker to fetch + ingest it. Naive HTTP GET would
happily hit ``http://169.254.169.254/latest/meta-data/…`` (AWS IMDS),
``http://localhost:5432`` (postgres), or ``http://10.0.0.5/admin``
(any internal service reachable from the container). This module
raises :class:`UnsafeUrlError` before any network I/O when the
target host resolves to a private range, and re-checks the target
on every redirect hop.

Reusable — future URL-crawling features (Meta / Google image
downloads, webhook target validation, OAuth redirect verification)
should route through this helper rather than call ``httpx`` directly.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class UnsafeUrlError(Exception):
    """Raised when a URL fails one of the SSRF-defence checks.

    Callers translate this to HTTP 422 with a stable ``reason`` code
    so tests + operators can distinguish scheme rejection from IP
    rejection from redirect abuse.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SafeFetchResult:
    """One successful fetch. ``final_url`` may differ from the
    input when the server issued redirects (all validated per-hop).
    """

    final_url: str
    status_code: int
    content: bytes
    content_type: str | None


_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_MAX_REDIRECTS: int = 5
_DEFAULT_TIMEOUT: float = 30.0


def _is_private_ip(ip_str: str) -> bool:
    """Return True for RFC1918, loopback, link-local, multicast,
    reserved, and unspecified addresses. Anything an internal
    service could sit behind."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — refuse defensively
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_host(host: str) -> list[str]:
    """DNS-resolve ``host`` to every A/AAAA address. Returns an
    empty list when the name doesn't resolve (caller treats as
    unsafe — a name that doesn't resolve today may resolve later
    and shouldn't be optimistically allowed)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.append(addr)
    return seen


def _validate_url(url: str) -> None:
    """Raise :class:`UnsafeUrlError` if the URL is unsafe to fetch.

    Enforces: http/https only, host must resolve, no resolved
    address may be private / loopback / link-local / reserved /
    multicast.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise UnsafeUrlError(str(exc), reason="malformed_url") from exc
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"only http / https are allowed, got {scheme!r}",
            reason="bad_scheme",
        )
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL has no host", reason="no_host")

    # Reject explicitly-formatted IP literals up front so we don't
    # even DNS-resolve them.
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and _is_private_ip(str(literal_ip)):
        raise UnsafeUrlError(
            f"IP literal {host} is in a private / reserved range",
            reason="private_ip_rejected",
        )

    # Resolve the hostname + refuse if any A/AAAA sits in a private
    # range. Prevents ``badguy.com`` from having an A record that
    # points at 10.0.0.1 (DNS rebinding is a related concern; the
    # per-hop re-check on redirect covers most of it).
    addresses = _resolve_host(host)
    if not addresses:
        raise UnsafeUrlError(
            f"host {host!r} did not resolve",
            reason="unresolvable_host",
        )
    for addr in addresses:
        if _is_private_ip(addr):
            raise UnsafeUrlError(
                f"host {host!r} resolves to private address {addr}",
                reason="private_ip_rejected",
            )


async def safe_fetch(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    max_redirects: int = _MAX_REDIRECTS,
    max_bytes: int = 90 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
) -> SafeFetchResult:
    """Fetch ``url`` with SSRF defence.

    * DNS-resolves + refuses private IPs BEFORE any network I/O.
    * Follows redirects up to ``max_redirects`` — re-validates each
      hop's target the same way (a public URL 301'ing to
      ``http://192.168.1.1`` is refused mid-flight).
    * Caps response size at ``max_bytes`` (default 90 MB matches
      the upload cap from Step 5 so URL ingest can't sneak past
      the file-size limit).

    Returns :class:`SafeFetchResult`. Raises :class:`UnsafeUrlError`
    for SSRF-relevant rejections; ``httpx.HTTPError`` for real
    network problems.
    """
    _validate_url(url)

    owned = client is None
    http = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        current_url = url
        for _ in range(max_redirects + 1):
            response = await http.get(current_url)
            # Redirect handling — re-validate the target host BEFORE
            # letting httpx follow. This is why we start with
            # ``follow_redirects=False``.
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                if not location:
                    return SafeFetchResult(
                        final_url=current_url,
                        status_code=response.status_code,
                        content=response.content,
                        content_type=response.headers.get("content-type"),
                    )
                # Resolve relative redirect against the current URL.
                if location.startswith("/"):
                    parsed_current = urlparse(current_url)
                    location = f"{parsed_current.scheme}://{parsed_current.netloc}{location}"
                _validate_url(location)
                current_url = location
                continue
            # Non-redirect — return.
            if len(response.content) > max_bytes:
                raise UnsafeUrlError(
                    f"response exceeded {max_bytes} bytes",
                    reason="response_too_large",
                )
            return SafeFetchResult(
                final_url=current_url,
                status_code=response.status_code,
                content=response.content,
                content_type=response.headers.get("content-type"),
            )
        raise UnsafeUrlError(
            f"too many redirects (> {max_redirects})",
            reason="too_many_redirects",
        )
    finally:
        if owned:
            await http.aclose()


__all__ = ["SafeFetchResult", "UnsafeUrlError", "safe_fetch"]
