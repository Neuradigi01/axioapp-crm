"""Trusted-proxy aware client-IP extraction.

The ``X-Forwarded-For`` header is CDN / load-balancer supplied and
carries the chain of hops as ``client, proxy1, proxy2``. Trusting
the leftmost value blindly is a well-known spoofing vector — an
attacker sends ``X-Forwarded-For: 8.8.8.8`` and their rate-limit
bucket is now indexed under Google's IP.

The canonical fix (nginx real-ip module, Cloudflare CF-Connecting-IP
docs, RFC 7239 §7.1) is to walk the header RIGHT-TO-LEFT starting
from the transport-level client address and stop at the first hop
that ISN'T in the operator-configured trusted-proxy list. That's
the caller we bill / rate-limit / audit.

When ``trusted_proxies`` is empty (dev shells, or an ops
misconfiguration) we DO NOT read ``X-Forwarded-For`` at all — we
return the raw TCP-level ``request.client.host``. That's the correct
fail-closed default because trusting a header nobody vouched for is
worse than losing the reverse-proxy hop.
"""

from __future__ import annotations

import ipaddress
import logging
from starlette.requests import Request

logger = logging.getLogger(__name__)


def parse_trusted_proxies(raw: str | None) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a comma-separated CIDR/IP string into a list of networks.

    Silently drops empty tokens; logs + drops malformed ones (a
    typo in the env var should degrade to "no proxies trusted" — the
    correct fail-closed default — rather than crash the API on boot).
    """
    if not raw:
        return []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            # ``strict=False`` accepts a plain IP (auto-widened to /32
            # or /128), which is what operators most often type.
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            logger.warning(
                "parse_trusted_proxies: dropping malformed CIDR %r", token
            )
    return networks


def _is_trusted(
    ip_text: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """True iff ``ip_text`` parses and matches one of the trusted
    networks."""
    if not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    for net in networks:
        if addr.version != net.version:
            continue
        if addr in net:
            return True
    return False


def parse_client_ip(
    request: Request,
    trusted_proxies: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> str:
    """Return the caller's IP, honouring ``X-Forwarded-For`` only when
    the transport-level client is a trusted proxy.

    Walks XFF right-to-left starting from the last hop; stops at the
    first non-trusted entry — that's the caller. If the whole chain
    is trusted (unusual but possible), returns the leftmost XFF
    entry. If no proxies are configured or the request came direct,
    returns ``request.client.host`` (or ``"unknown"`` as a last
    resort so callers never have to check for None).
    """
    peer = request.client.host if request.client else None

    if not trusted_proxies or not peer or not _is_trusted(peer, trusted_proxies):
        return peer or "unknown"

    xff = request.headers.get("x-forwarded-for") or ""
    if not xff:
        return peer

    hops = [h.strip() for h in xff.split(",") if h.strip()]
    if not hops:
        return peer

    # Walk right to left. First non-trusted hop is the caller.
    for hop in reversed(hops):
        if not _is_trusted(hop, trusted_proxies):
            return hop
    # Every hop is trusted — return the leftmost (the original
    # visitor as the first proxy saw them).
    return hops[0]


__all__ = ["parse_client_ip", "parse_trusted_proxies"]
