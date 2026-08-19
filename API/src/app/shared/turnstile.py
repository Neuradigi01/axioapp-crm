"""Cloudflare Turnstile server-side verifier
(``tasks/ai-assistants`` Step 14).

Verifies a client-submitted Turnstile token against Cloudflare's
``siteverify`` endpoint. Used by the AI-assistants public router
to gate the first message per session — subsequent messages within
the same session skip the check (see the session-token cache in
:mod:`~core.ai_assistants.public_router`).

Dev bypass tokens (``1x0000000000000000000000000000000AA`` +
friends) are Cloudflare-documented always-pass values — the
``siteverify`` endpoint accepts them when the request uses the
test secret ``1x0000000000000000000000000000000AA``. We short-
circuit locally when :envvar:`TURNSTILE_SECRET_KEY` is empty so
smoke-testing without any Cloudflare setup works.

Timeouts are aggressive (3s) — a slow Cloudflare should not make
the chat widget unresponsive. On timeout / network error we FAIL
CLOSED (return False) since Turnstile is one of the last-mile
defences against widget abuse.
"""

from __future__ import annotations

import logging

import httpx

from config import TURNSTILE_SECRET_KEY

logger = logging.getLogger(__name__)

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TIMEOUT_SECONDS = 3.0

# Cloudflare's documented always-pass test tokens. Only trusted when
# TURNSTILE_SECRET_KEY is empty (dev / smoke mode) so a production
# misconfiguration doesn't inadvertently accept these.
_DEV_BYPASS_TOKENS: frozenset[str] = frozenset(
    {
        "1x0000000000000000000000000000000AA",
        "2x0000000000000000000000000000000AA",
    }
)


async def verify_turnstile(
    token: str | None,
    *,
    remote_ip: str | None = None,
) -> bool:
    """Verify a Turnstile ``cf-turnstile-response`` token.

    Returns True on success. Fails closed (returns False) on:
      * Missing / empty token.
      * Cloudflare rejection (any ``error-codes`` present).
      * Network / HTTP error.
      * Timeout.

    Dev mode (empty :envvar:`TURNSTILE_SECRET_KEY`) accepts documented
    bypass tokens without a network round-trip so local + CI smoke
    tests don't need Cloudflare credentials.
    """
    if not token:
        return False

    secret = TURNSTILE_SECRET_KEY.strip()
    if not secret:
        # Dev / smoke mode — accept known bypass tokens only.
        return token in _DEV_BYPASS_TOKENS

    data: dict[str, str] = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(_SITEVERIFY_URL, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("turnstile.verify network_error err=%r", exc)
        return False

    if resp.status_code != 200:
        logger.warning("turnstile.verify http_error status=%s", resp.status_code)
        return False

    try:
        payload = resp.json()
    except ValueError:
        logger.warning("turnstile.verify malformed_response")
        return False

    success = bool(payload.get("success"))
    if not success:
        codes = payload.get("error-codes") or []
        logger.info("turnstile.verify rejected codes=%r", codes)
    return success


__all__ = ["verify_turnstile"]
