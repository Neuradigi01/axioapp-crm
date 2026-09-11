"""Startup-time configuration validation.

Called from ``main.lifespan`` before the app accepts traffic.
Anything that MUST be set in production (and whose absence would
silently degrade a security control) raises here so uvicorn refuses
to serve rather than boot into a broken state.

Rules:

* ``TRUSTED_PROXIES`` MUST be non-empty when ``IS_DEVELOPMENT=false``.
  An empty list means the XFF parser falls back to the transport-level
  client IP — behind a reverse proxy that's the proxy's own address,
  collapsing every public-ingest request into a single per-IP bucket.
  A malicious caller then trivially exhausts the rate limit for every
  other visitor. Fail-loud so ops sees the misconfiguration on the
  first restart rather than in the middle of an incident.

Dev boot (``IS_DEVELOPMENT=true``) skips this check — local shells
run without a reverse proxy and TRUSTED_PROXIES=empty is the correct
value there.
"""

from __future__ import annotations

import logging

from config import IS_DEVELOPMENT, TRUSTED_PROXIES
from src.app.shared.http.client_ip import parse_trusted_proxies

logger = logging.getLogger(__name__)


class StartupCheckFailed(RuntimeError):
    """Raised when a mandatory configuration invariant is violated
    at boot. The lifespan handler re-raises so uvicorn logs the reason
    and exits — a partially-configured API must NOT accept traffic."""


def check_trusted_proxies() -> None:
    """TRUSTED_PROXIES MUST be non-empty in production."""
    parsed = parse_trusted_proxies(TRUSTED_PROXIES)
    if IS_DEVELOPMENT:
        if not parsed:
            logger.info(
                "startup_checks: TRUSTED_PROXIES is empty (IS_DEVELOPMENT=true — OK)"
            )
        else:
            logger.info(
                "startup_checks: TRUSTED_PROXIES parsed into %d network(s)", len(parsed)
            )
        return
    if not parsed:
        raise StartupCheckFailed(
            "TRUSTED_PROXIES is empty in production. Set to the reverse-proxy "
            "IP/CIDR (comma-separated) in config.env or the API refuses to boot "
            "— see docs/public-ingest.md."
        )
    logger.info(
        "startup_checks: TRUSTED_PROXIES parsed into %d network(s)", len(parsed)
    )


def run_all() -> None:
    """Run every startup check in order. Called from ``main.lifespan``."""
    check_trusted_proxies()


__all__ = ["StartupCheckFailed", "check_trusted_proxies", "run_all"]
