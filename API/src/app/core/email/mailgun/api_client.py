"""One seam that speaks to Mailgun's Domains API.

Every ``core/email_sender_setup/`` write path goes through this client
— nothing else touches Mailgun for domain management. Keeps the retry
policy, region routing, and response-shape validation in one place so
Track 4's reputation tasks (which will re-use the same client for
different endpoints) don't repeat the pattern.

Discovery notes: ``tasks/email-sending-domains/DISCOVERY-NOTES.md``.
Confirms endpoints are on **`/v4/domains/*`** (not `/v3/*` as an
earlier plan draft assumed) and DnsRecord fields per the official
mailgun-php SDK: ``record_type``, ``name``, ``value``, ``priority``,
``valid``, ``cached``, ``is_active``.

Retry policy: 502 and 503 are retried up to 2 times with exponential
backoff (0.5 s, then 1.0 s). Every other 5xx surfaces as
:class:`MailgunProviderError` immediately — 500 typically means
Mailgun's own bug, and retrying just amplifies the impact. 4xx is
never retried; the caller sees the specific exception subclass.

Regional base URLs:
  * ``us`` → ``https://api.mailgun.net`` (verified in DISCOVERY-NOTES).
  * ``eu`` → ``https://api.eu.mailgun.net`` (**UNVERIFIED at
    discovery time** — SDK's ``create()`` accepts arbitrary
    ``$endpoint`` and doesn't hard-code an EU URL. Widely known,
    but flag when EU-region tenants land).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from src.app.core.email.mailgun.api_client_errors import (
    MailgunApiError,
    MailgunAuthError,
    MailgunNotFound,
    MailgunProviderError,
    MailgunRateLimited,
    MailgunResponseInvalid,
)

logger = logging.getLogger(__name__)


# Regional base URLs. Kept as module-level constants so tests can
# monkey-patch a fixture host without touching the class internals.
BASE_URL_US = "https://api.mailgun.net"
BASE_URL_EU = "https://api.eu.mailgun.net"

_REGION_TO_BASE = {
    "us": BASE_URL_US,
    "eu": BASE_URL_EU,
}

# Retry policy. 502/503 are retried; everything else surfaces
# immediately. Two retries with exponential backoff (0.5s → 1s)
# balance transient-blip absorption against operator visibility on
# a real Mailgun outage.
_RETRYABLE_STATUS_CODES = frozenset({502, 503})
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = (0.5, 1.0)

# Hard timeout per request. Mailgun's median latency on GET/POST
# /v4/domains sits comfortably under 2s; 10s catches the tail without
# blocking a webhook's request path when the client is called inline.
_REQUEST_TIMEOUT_SECONDS = 10.0

# Body-preview cap on error paths — avoids Mailgun HTML error pages
# filling the logs.
_ERROR_BODY_PREVIEW_MAX = 500


# ---------------------------------------------------------------------------
# Response models — Pydantic v2
# ---------------------------------------------------------------------------


class DnsRecord(BaseModel):
    """One row of Mailgun's ``sending_dns_records`` /
    ``receiving_dns_records`` arrays. Every field nullable because
    Mailgun sometimes omits per record type (e.g. ``priority`` is only
    populated for MX rows).
    """

    model_config = ConfigDict(extra="allow")

    record_type: str | None = None
    name: str | None = None
    value: str | None = None
    priority: str | None = None
    valid: str | None = None
    cached: list[Any] | None = None
    is_active: bool | None = None


class DomainDetail(BaseModel):
    """Parsed shape of ``GET /v4/domains/{name}`` and
    ``PUT /v4/domains/{name}/verify``. Callers persist
    ``sending_dns_records`` + ``receiving_dns_records`` verbatim
    into the ``tbl_organization_email_domains.dns_records`` JSONB.
    """

    model_config = ConfigDict(extra="allow")

    mailgun_domain_id: str
    name: str
    state: str | None = None
    type: str | None = None
    created_at: str | None = None
    sending_dns_records: list[dict[str, Any]]
    receiving_dns_records: list[dict[str, Any]]


class DomainCreateResult(DomainDetail):
    """Shape of ``POST /v4/domains``.

    Currently identical to :class:`DomainDetail` — the SDK
    (DISCOVERY-NOTES §4) doesn't distinguish. Separate class so the
    caller's type hint reflects the create vs. show intent + a future
    contract drift lands as one narrow edit.
    """


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


Region = Literal["us", "eu"]


class MailgunApiClient:
    """Async httpx wrapper for Mailgun's Domains API.

    Constructor takes a region string; if not passed, reads
    ``MAILGUN_REGION`` env (default ``"us"``). The API key is always
    read from ``MAILGUN_API_KEY`` — never from the constructor —
    because leaking a caller-scoped key is a class of mistake the
    module boundary should prevent.

    Not a singleton: one instance per code path is fine. httpx handles
    connection pooling internally.
    """

    def __init__(
        self,
        *,
        region: Region | None = None,
        timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_region = region or os.getenv("MAILGUN_REGION", "us").strip().lower()
        if resolved_region not in _REGION_TO_BASE:
            raise ValueError(
                f"unknown MAILGUN_REGION {resolved_region!r} — expected 'us' or 'eu'"
            )
        self._region = resolved_region
        self._base_url = _REGION_TO_BASE[resolved_region]
        self._timeout = timeout_seconds
        # Only tests inject a transport (typically ``httpx.MockTransport``);
        # production leaves it None so ``httpx.AsyncClient`` uses its
        # default connection-pooling HTTP/1.1 transport.
        self._transport = transport

    @property
    def region(self) -> str:
        return self._region

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_domain(
        self,
        domain: str,
        *,
        dkim_key_size: int = 2048,
    ) -> DomainCreateResult:
        """``POST /v4/domains``. Returns the parsed create result.

        ``dkim_key_size`` defaults to 2048 (SDK default is 1024;
        we upgrade for defense-in-depth).
        """
        payload = {"name": domain, "dkim_key_size": str(dkim_key_size)}
        body = await self._request(
            "POST", "/v4/domains", data=payload
        )
        return _parse_domain_body(body, expected_class=DomainCreateResult)

    async def get_domain(self, domain: str) -> DomainDetail:
        """``GET /v4/domains/{name}``. Returns the fresh detail body."""
        body = await self._request("GET", f"/v4/domains/{domain}")
        return _parse_domain_body(body, expected_class=DomainDetail)

    async def verify_domain(self, domain: str) -> DomainDetail:
        """``PUT /v4/domains/{name}/verify`` — forces a fresh DNS check
        + returns updated state."""
        body = await self._request("PUT", f"/v4/domains/{domain}/verify")
        return _parse_domain_body(body, expected_class=DomainDetail)

    async def delete_domain(self, domain: str) -> None:
        """``DELETE /v4/domains/{name}``. 404 is treated as success
        (idempotent — the caller's intent is "make it gone")."""
        try:
            await self._request("DELETE", f"/v4/domains/{domain}")
        except MailgunNotFound:
            return

    # ------------------------------------------------------------------
    # Internal — HTTP + retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        api_key = os.getenv("MAILGUN_API_KEY", "").strip()
        if not api_key:
            raise MailgunAuthError(
                "MAILGUN_API_KEY is not configured", status_code=None
            )

        last_error: httpx.HTTPError | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                client_kwargs: dict[str, Any] = dict(
                    auth=("api", api_key),
                    base_url=self._base_url,
                    timeout=self._timeout,
                )
                if self._transport is not None:
                    client_kwargs["transport"] = self._transport
                async with httpx.AsyncClient(**client_kwargs) as client:
                    if data is not None:
                        response = await client.request(method, path, data=data)
                    else:
                        response = await client.request(method, path)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
                    continue
                raise MailgunProviderError(
                    f"mailgun request failed after {attempt + 1} attempts: {exc}",
                    status_code=None,
                ) from exc

            status = response.status_code
            body_preview = response.text[:_ERROR_BODY_PREVIEW_MAX]

            if status == 200 or status == 201:
                return _parse_json_body(response, status=status)

            if status == 401:
                raise MailgunAuthError(
                    "mailgun rejected the API key (401)",
                    status_code=status,
                    body_preview=body_preview,
                )
            if status == 404:
                raise MailgunNotFound(
                    f"mailgun 404 for {method} {path}",
                    status_code=status,
                    body_preview=body_preview,
                )
            if status == 429:
                retry_after = _parse_retry_after(response)
                raise MailgunRateLimited(
                    "mailgun rate limited (429)",
                    status_code=status,
                    body_preview=body_preview,
                    retry_after_seconds=retry_after,
                )
            if status in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                logger.warning(
                    "mailgun_api_client.retry status=%d attempt=%d method=%s path=%s",
                    status,
                    attempt + 1,
                    method,
                    path,
                )
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
                continue
            if 500 <= status < 600:
                raise MailgunProviderError(
                    f"mailgun {status} for {method} {path}",
                    status_code=status,
                    body_preview=body_preview,
                )
            # Any other 4xx we haven't specifically handled.
            raise MailgunApiError(
                f"mailgun unexpected {status} for {method} {path}",
                status_code=status,
                body_preview=body_preview,
            )

        # Loop-exit safety net — should never reach here because the
        # last attempt either returns, raises, or propagates.
        raise MailgunProviderError(
            f"mailgun request exhausted retries: {last_error}",
            status_code=None,
        )


# ---------------------------------------------------------------------------
# Body parsers — module-level so tests can exercise them directly.
# ---------------------------------------------------------------------------


def _parse_json_body(response: httpx.Response, *, status: int) -> dict[str, Any]:
    """Return the response body as a dict.

    Raises :class:`MailgunResponseInvalid` when the body isn't JSON or
    isn't a top-level object. Mailgun's 2xx responses are always
    ``application/json``; deviating from that is a signal an
    intermediary (edge cache, WAF) hijacked the response.
    """
    try:
        body = response.json()
    except ValueError as exc:
        raise MailgunResponseInvalid(
            f"mailgun {status} response was not valid JSON",
            status_code=status,
            body_preview=response.text[:_ERROR_BODY_PREVIEW_MAX],
        ) from exc
    if not isinstance(body, dict):
        raise MailgunResponseInvalid(
            f"mailgun {status} JSON body was not an object",
            status_code=status,
            body_preview=response.text[:_ERROR_BODY_PREVIEW_MAX],
        )
    return body


def _parse_domain_body(
    body: dict[str, Any],
    *,
    expected_class: type[DomainDetail],
) -> DomainDetail:
    """Build the response Pydantic model from Mailgun's envelope.

    Envelope shape (verified in DISCOVERY-NOTES §GET response envelope):

        {
          "domain":               {"id": "...", "name": "...", "state": "...", ...},
          "sending_dns_records":  [ ... ],
          "receiving_dns_records":[ ... ],
        }

    We flatten ``domain.id`` → ``mailgun_domain_id`` so the caller
    doesn't need to reach into the nested object; everything else
    keeps its Mailgun name.
    """
    domain_obj = body.get("domain")
    sending = body.get("sending_dns_records")
    receiving = body.get("receiving_dns_records")
    if (
        not isinstance(domain_obj, dict)
        or not isinstance(sending, list)
        or not isinstance(receiving, list)
    ):
        raise MailgunResponseInvalid(
            "mailgun response missing expected domain/sending/receiving keys",
            status_code=None,
        )
    mailgun_id = domain_obj.get("id")
    name = domain_obj.get("name")
    if not isinstance(mailgun_id, str) or not isinstance(name, str):
        raise MailgunResponseInvalid(
            "mailgun response domain.id / domain.name missing or wrong type",
            status_code=None,
        )
    return expected_class(
        mailgun_domain_id=mailgun_id,
        name=name,
        state=domain_obj.get("state"),
        type=domain_obj.get("type"),
        created_at=domain_obj.get("created_at"),
        sending_dns_records=sending,
        receiving_dns_records=receiving,
    )


def _parse_retry_after(response: httpx.Response) -> int | None:
    """Extract the ``Retry-After`` header if present + parseable as int."""
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return max(0, int(header))
    except ValueError:
        return None


__all__ = [
    "BASE_URL_EU",
    "BASE_URL_US",
    "DnsRecord",
    "DomainCreateResult",
    "DomainDetail",
    "MailgunApiClient",
    "Region",
]
