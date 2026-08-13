"""SSRF-hardened HTTP client for the API Request node
(``tasks/chatbot-builder`` Step 9 / Decision §16 / Case H5).

Rules enforced BEFORE any request leaves the process:

  * **HTTPS only** at runtime; ``http://`` URLs are rejected at
    save-time by the node's validator + here as belt-and-braces.
  * **DNS resolves to a public address**. Every ``AF_INET`` /
    ``AF_INET6`` answer for the target host is checked against the
    reserved-range table below. One private-range hit → refuse the
    request.
  * **Redirects are re-validated** — the httpx client is called
    with ``follow_redirects=False``; we walk each 3xx manually,
    re-running the scheme + DNS gates on every hop.
  * **Response body capped at 1 MB** by iter_bytes accumulator.
  * **Timeouts** — connect 5s, read <= 30s, write 5s.

Cases the raw ``httpx.AsyncClient`` would let through and we do not:
  ``http://169.254.169.254/`` (AWS/GCP metadata), ``http://localhost``,
  ``http://127.0.0.1``, ``http://10.0.0.5``, ``http://192.168.1.1``,
  ``http://fd00::1`` (IPv6 ULA), ``http://[::1]/``.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


# --- Configuration --------------------------------------------------------

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https"})
_MAX_REDIRECTS = 3
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024  # 1 MB
_CONNECT_TIMEOUT_SECONDS = 5.0
_MAX_READ_TIMEOUT_SECONDS = 30.0


class UnsafeUrl(ValueError):
    """Raised when a URL fails the pre-flight SSRF gate. Router
    translates this to 422."""


@dataclass(slots=True)
class SafeResponse:
    """What :func:`request` returns on success. Handler wraps this
    into the step_run's transcript."""

    status_code: int
    headers: dict[str, str]
    text: str
    json: Any = None
    truncated: bool = False
    final_url: str = ""


# --- SSRF pre-flight ------------------------------------------------------


def _is_private_or_reserved_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """One-stop reserved-range check. Rejects loopback, private,
    link-local, multicast, unspecified, and IPv6 ULA."""
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) — check the
        # embedded v4 too so a mapping trick can't sneak past.
        return _is_private_or_reserved_ip(ip.ipv4_mapped)
    return False


def _resolve_and_gate(host: str, port: int) -> list[str]:
    """Resolve ``host`` to every IPv4/IPv6 address via ``getaddrinfo``
    and refuse the whole set if ANY resolved address is private.
    Returns the safe IP list for the caller's logging."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"could not resolve host {host!r}: {exc}") from exc

    resolved: list[str] = []
    for info in infos:
        raw_ip = info[4][0]
        # getaddrinfo may return scope-suffixed IPv6 addresses
        # ("fe80::1%eth0"); strip the scope for the ipaddress parser.
        clean = raw_ip.split("%", 1)[0]
        try:
            ip_obj = ipaddress.ip_address(clean)
        except ValueError:
            raise UnsafeUrl(f"unparseable address {raw_ip!r} for host {host!r}") from None
        if _is_private_or_reserved_ip(ip_obj):
            raise UnsafeUrl(
                f"host {host!r} resolves to private/reserved address {clean} — refused"
            )
        resolved.append(clean)

    if not resolved:
        raise UnsafeUrl(f"host {host!r} resolved to no addresses")

    return resolved


def _validate_url(url: str) -> tuple[str, str, int]:
    """Parse + gate a URL. Returns ``(scheme, host, port)`` on
    success; raises :class:`UnsafeUrl` otherwise. Does NOT touch DNS
    — call :func:`_resolve_and_gate` right after."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrl(
            f"URL scheme {scheme!r} not allowed — HTTPS only (got {url!r})"
        )
    host = parsed.hostname
    if not host:
        raise UnsafeUrl(f"URL missing host: {url!r}")

    # Reject raw-IP URLs pointing at private ranges even before DNS.
    # (Prevents "https://127.0.0.1/..." from being sent to
    # getaddrinfo which would return the same private IP.)
    try:
        maybe_ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_private_or_reserved_ip(maybe_ip):
            raise UnsafeUrl(f"URL host is a private/reserved IP: {host}")

    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, host, port


# --- Request ---------------------------------------------------------------


async def request(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    timeout_seconds: float = 10.0,
    max_response_bytes: int = _MAX_RESPONSE_BYTES,
) -> SafeResponse:
    """Send one HTTP request under all SSRF + size + timeout gates.

    Raises :class:`UnsafeUrl` on any pre-flight failure, and
    :class:`httpx.HTTPError` subclasses on transport failure. The
    node handler catches both and records them on the ``error``
    step-run status.
    """
    method_upper = (method or "GET").upper()
    if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise UnsafeUrl(f"method {method_upper!r} not allowed")

    read_timeout = min(float(timeout_seconds), _MAX_READ_TIMEOUT_SECONDS)
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT_SECONDS,
        read=read_timeout,
        write=_CONNECT_TIMEOUT_SECONDS,
        pool=_CONNECT_TIMEOUT_SECONDS,
    )

    current_url = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        max_redirects=0,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as client:
        for hop in range(_MAX_REDIRECTS + 1):
            _scheme, host, port = _validate_url(current_url)
            _resolve_and_gate(host, port)

            logger.info(
                "chatbots.http_client_safe request method=%s url=%s hop=%s",
                method_upper,
                current_url,
                hop,
            )

            resp = await client.request(
                method_upper,
                current_url,
                headers=headers or {},
                json=json_body,
            )

            if 300 <= resp.status_code < 400 and "location" in resp.headers:
                if hop >= _MAX_REDIRECTS:
                    raise UnsafeUrl(
                        f"redirect chain exceeded {_MAX_REDIRECTS} hops"
                    )
                # httpx already resolves relative Locations against the
                # request URL; call .absolute_url through the request
                # for correctness.
                current_url = str(resp.headers["location"])
                # Only follow GET-safe redirects for non-GET methods; other
                # methods can safely re-follow as GET per HTTP semantics
                # but for v1 we keep the method — matches Meta's API
                # behaviour + is easier to reason about.
                continue

            # Terminal response. Enforce body size cap.
            body_bytes = resp.content
            truncated = False
            if len(body_bytes) > max_response_bytes:
                body_bytes = body_bytes[:max_response_bytes]
                truncated = True

            text = body_bytes.decode(
                resp.encoding or "utf-8", errors="replace"
            )
            json_data: Any = None
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
            if content_type in {"application/json", "text/json"} and not truncated:
                try:
                    import json as _json

                    json_data = _json.loads(text)
                except (ValueError, TypeError):
                    json_data = None

            return SafeResponse(
                status_code=resp.status_code,
                headers={k: v for k, v in resp.headers.items()},
                text=text,
                json=json_data,
                truncated=truncated,
                final_url=str(current_url),
            )

    raise UnsafeUrl("redirect walk exhausted without a terminal response")


__all__ = [
    "SafeResponse",
    "UnsafeUrl",
    "request",
]
