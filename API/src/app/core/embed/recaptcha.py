"""Server-side Google reCAPTCHA v3 verification.

`verify_token` is the single entry point. It POSTs to Google's
`siteverify` endpoint, parses the response, and returns True iff:

  - `success` is True (the token wasn't forged / expired / re-used)
  - `score` is at or above the configured threshold (default 0.5 —
    Google's recommended cutoff for "probably human")
  - `action` matches the expected action string (the widget always
    submits with `action="submit"`; mismatch suggests the token was
    minted by a different flow on the same site key)

Failure modes — all fail closed (return False), so the caller silent-
drops the submission:

  - HTTP error from Google (5xx, timeout): can't prove the user is
    human → don't admit them.
  - Malformed response body: same — fail closed.
  - Score below threshold: probable bot.
  - Action mismatch: token meant for a different flow.

This is *defence in depth* — even if Google's API is degraded, the
honeypot + min-time gates already filter most volume; reCAPTCHA is
the last spam wall, and it's better to lose a small fraction of real
submissions during a Google outage than to flood the CRM with bots.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
DEFAULT_SCORE_THRESHOLD = 0.5
DEFAULT_TIMEOUT_SECONDS = 5.0


async def verify_token(
    *,
    token: str,
    secret: str,
    expected_action: str = "submit",
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    remote_ip: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> bool:
    """Verify a reCAPTCHA v3 token against Google's siteverify API.

    Returns True iff Google's response indicates the token is valid,
    the score is at or above `score_threshold`, and the action matches
    `expected_action`. Returns False on any HTTP / parse / threshold
    failure — the caller's silent-200 path then absorbs the rejection.

    `http_client` is optional — tests inject a fixture client; production
    callers should pass None and let this function manage the lifecycle
    of a per-request httpx client (cheap; siteverify is rare relative
    to submission volume since most submissions short-circuit on the
    honeypot or min-time gate before reaching here).
    """
    data: dict[str, str] = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        if http_client is not None:
            response = await http_client.post(VERIFY_URL, data=data)
        else:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                response = await client.post(VERIFY_URL, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        # Network / DNS / timeout / TLS failure — Google unreachable.
        # Fail closed: we can't prove the user is human.
        logger.warning("recaptcha.verify network error: %s", exc)
        return False

    if response.status_code != 200:
        logger.warning(
            "recaptcha.verify non-200 status=%d body=%s",
            response.status_code,
            response.text[:200],
        )
        return False

    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        logger.warning("recaptcha.verify body wasn't JSON")
        return False

    success = bool(body.get("success"))
    score = float(body.get("score", 0.0) or 0.0)
    action = str(body.get("action", "") or "")

    if not success:
        logger.info(
            "recaptcha.verify rejected: success=false errors=%s",
            body.get("error-codes"),
        )
        return False
    if score < score_threshold:
        logger.info(
            "recaptcha.verify rejected: score=%.2f < threshold=%.2f",
            score,
            score_threshold,
        )
        return False
    if action != expected_action:
        logger.info(
            "recaptcha.verify rejected: action=%r expected=%r",
            action,
            expected_action,
        )
        return False
    return True


__all__ = ["DEFAULT_SCORE_THRESHOLD", "VERIFY_URL", "verify_token"]
