"""Slack incoming-webhook client — single async function.

Slack's incoming-webhook protocol is a POST to a private URL with
JSON ``{"text": "..."}``. The response body is a literal "ok" on
success. Anything else is a 4xx/5xx + descriptive body the operator
needs to see; we raise :class:`SlackError` carrying the response
text so the workflow run-history view surfaces it.

We don't use the rich Block Kit API yet — :func:`post_message`
ships only the plain-text body the operator authors in the
template. When operators ask for rich-format Slack messages, we'll
extend the contract to accept ``blocks: list[dict]`` too without
breaking call sites.

Timeout: 10 seconds. Workflow Send actions are queued via Celery
so a slow Slack endpoint won't block a request thread; the
timeout exists just to bound the worker hold-time when Slack is
flat-out down.
"""
from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SECONDS = 10.0
_MAX_TEXT_LEN = 40000  # Slack's hard cap is ~40k chars.


class SlackError(Exception):
    """Raised when the Slack webhook returns non-200 or the request
    itself fails (timeout / network error). Carries the response
    text + status code when available."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def post_message(
    webhook_url: str,
    text: str,
    *,
    idempotency_key: str | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """POST ``{"text": text}`` to ``webhook_url``. Raises
    :class:`SlackError` on any failure; returns ``None`` on success.

    ``idempotency_key`` — when set, attached as the
    ``X-Idempotency-Key`` request header so a Celery retry of the
    same step_run doesn't repost. Slack itself ignores this header
    today but the upstream proxy / future native support keeps the
    contract stable.
    """
    if not isinstance(webhook_url, str) or not webhook_url.startswith(
        "https://"
    ):
        raise SlackError("webhook_url must be an https:// URL")
    if not isinstance(text, str) or not text.strip():
        raise SlackError("text must be a non-empty string")
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN]

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    # Local import so the module loads without httpx in dev shells
    # that never invoke the Slack path.
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover — httpx is pinned in prod.
        raise SlackError(f"httpx not installed: {exc}") from exc

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            response = await client.post(
                webhook_url,
                json={"text": text},
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise SlackError(f"slack webhook timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise SlackError(f"slack webhook error: {exc}") from exc

    if response.status_code >= 300:
        raise SlackError(
            f"slack webhook returned {response.status_code}: "
            f"{response.text[:500]}",
            status_code=response.status_code,
        )

    body = (response.text or "").strip().lower()
    if body and body != "ok":
        # Slack returns "ok" on success; any other 2xx body is unexpected
        # but harmless — log + return.
        logger.info(
            "slack.post_message unexpected_success_body body=%r", body
        )


__all__ = ["SlackError", "post_message"]
