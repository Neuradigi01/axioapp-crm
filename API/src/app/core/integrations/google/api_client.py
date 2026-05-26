"""Google Ads REST client — thin httpx wrapper over the subset of
v17 endpoints we actually call (`listAccessibleCustomers` +
`googleAds:searchStream` for lead-form extension feed items).

**SDK vs REST decision:** the official `google-ads` Python SDK pulls
in gRPC, protobuf, and ~50 MB of transitive dependencies for what is,
for us, two HTTP endpoints. The REST surface is a stable, documented
alternative (https://developers.google.com/google-ads/api/rest/overview)
and the marginal effort of hand-rolling the two requests is far less
than the cost of carrying the SDK in our deps. Decision: REST via
httpx. If we ever need streaming, real-time mutate operations, or
the metric reporting surface, we revisit.

The client is short-lived: instantiate per-request, make one or two
calls, throw away. Each call lazily refreshes the access token if the
stored one is within 60 seconds of expiry — keeping refresh inside
the client (rather than in a separate cron) means stale-token errors
literally cannot reach the caller.

`integration.access_token_enc` / `refresh_token_enc` are the source
of truth. After a refresh, we re-encrypt the new access token + the
new expiry and persist; the caller's session commits it.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    GOOGLE_ADS_API_VERSION,
    GOOGLE_ADS_DEVELOPER_TOKEN,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
)
from src.app.core.integrations.crypto import decrypt, encrypt
from src.app.core.integrations.models import (
    Integration,
    IntegrationStatus,
)


_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://googleads.googleapis.com"
_HTTP_TIMEOUT = 15.0

# Refresh the access token if it expires within this many seconds.
# Wider than zero so a slow call doesn't race with the expiry boundary.
_REFRESH_LEEWAY_SECONDS = 60


class GoogleAdsRestClient:
    """Stateful per-request client. Holds the `Integration` row + a
    DB session for the rare write that happens when a token refresh
    rotates credentials. Callers create one, make their calls, and
    drop the reference.

    `http_client` is injectable for tests — production callers pass
    None and get a fresh httpx client per call (cheap).
    """

    def __init__(
        self,
        *,
        integration: Integration,
        session: AsyncSession,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if integration.status != IntegrationStatus.connected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Google integration is {integration.status.value} — "
                    "reconnect required."
                ),
            )
        if not GOOGLE_ADS_DEVELOPER_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "GOOGLE_ADS_DEVELOPER_TOKEN not configured — see "
                    "Stage 4 of "
                    "tasks/ad-integrations/manual-google-oauth-setup.md."
                ),
            )
        self._integration = integration
        self._session = session
        self._http = http_client

    # --- public surface -------------------------------------------------

    async def get(
        self, path: str, *, login_customer_id: Optional[str] = None
    ) -> dict:
        """GET an API path, returning the decoded JSON. Raises
        HTTPException with the upstream status code on non-2xx."""
        return await self._request(
            "GET", path, login_customer_id=login_customer_id
        )

    async def post(
        self,
        path: str,
        *,
        json: dict,
        login_customer_id: Optional[str] = None,
    ) -> dict:
        """POST JSON, return decoded JSON. Same error semantics as `get`."""
        return await self._request(
            "POST",
            path,
            json=json,
            login_customer_id=login_customer_id,
        )

    # --- private --------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        login_customer_id: Optional[str] = None,
    ) -> dict:
        access_token = await self._get_access_token()
        url = f"{_API_BASE}/{GOOGLE_ADS_API_VERSION}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": GOOGLE_ADS_DEVELOPER_TOKEN,
            "Content-Type": "application/json",
        }
        # `login-customer-id` is required when calling on behalf of a
        # Manager (MCC) account. For non-MCC users it must be OMITTED
        # — sending it pointing at a non-manager triggers an INVALID_
        # CUSTOMER_ID error from the API. Caller-controlled.
        if login_customer_id:
            headers["login-customer-id"] = login_customer_id.replace("-", "")

        try:
            response = await self._http_call(
                method, url, headers=headers, json=json
            )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Google Ads API unreachable: {exc}",
            ) from exc

        if response.status_code >= 400:
            detail = _safe_json(response) or {"raw": response.text[:300]}
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Google Ads API error (status={response.status_code}): "
                    f"{detail}"
                ),
            )
        # Some endpoints (e.g. searchStream) can return an empty array;
        # JSON decode still works.
        body = _safe_json(response)
        return body if body is not None else {}

    async def _http_call(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json: Optional[dict],
    ) -> httpx.Response:
        if self._http is not None:
            return await self._http.request(
                method, url, headers=headers, json=json
            )
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            return await client.request(
                method, url, headers=headers, json=json
            )

    async def _get_access_token(self) -> str:
        """Return a usable access token, refreshing transparently if
        the stored one is expired or expiring soon. Updates the
        integration row + commits the session when a refresh happens.
        """
        if (
            self._integration.token_expires_at is not None
            and _expires_in_more_than(
                self._integration.token_expires_at,
                _REFRESH_LEEWAY_SECONDS,
            )
            and self._integration.access_token_enc
        ):
            return decrypt(self._integration.access_token_enc)

        # Refresh path. Requires a stored refresh token — Google's
        # access tokens are short-lived (1 hour) and can't be re-used
        # past expiry without exchanging the refresh token.
        if not self._integration.refresh_token_enc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Google integration has no refresh token — "
                    "disconnect and reconnect to re-establish "
                    "long-lived access."
                ),
            )
        refresh_token = decrypt(self._integration.refresh_token_enc)
        # Google's token endpoint requires form-encoded data, not JSON —
        # `_post_refresh` does the right call shape rather than going
        # through the generic `_http_call` JSON path.
        try:
            response = await self._post_refresh(refresh_token)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Google token endpoint unreachable: {exc}",
            ) from exc

        if response.status_code != 200:
            # Mark the integration `expired` so the Settings UI can
            # surface the reconnect CTA. We don't raise the original
            # body — Google sometimes returns generic 401s here.
            self._integration.status = IntegrationStatus.expired
            self._integration.last_error = (
                f"refresh failed status={response.status_code}"
            )
            await self._session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google refused the refresh token — reconnect.",
            )

        body = _safe_json(response) or {}
        new_access = body.get("access_token")
        if not new_access:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Refresh response missing access_token.",
            )
        new_expiry = int(time.time()) + int(body.get("expires_in", 3600))

        # Persist the rotated credentials. Google sometimes rotates the
        # refresh token; honour it if present.
        self._integration.access_token_enc = encrypt(new_access)
        self._integration.token_expires_at = datetime.fromtimestamp(
            new_expiry, tz=timezone.utc
        )
        rotated_refresh = body.get("refresh_token")
        if rotated_refresh:
            self._integration.refresh_token_enc = encrypt(rotated_refresh)
        self._integration.status = IntegrationStatus.connected
        self._integration.last_error = None
        await self._session.commit()
        return new_access

    async def _post_refresh(self, refresh_token: str) -> httpx.Response:
        """Stand-alone refresh POST. Kept separate from `_http_call`
        because httpx wants form-encoded data here (not JSON) — Google's
        token endpoint is one of the few that's strict about it."""
        data = {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if self._http is not None:
            return await self._http.post(_TOKEN_URL, data=data)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            return await client.post(_TOKEN_URL, data=data)


def _expires_in_more_than(expires_at: datetime, seconds: int) -> bool:
    """True iff the token is still good for at least `seconds` more."""
    now = datetime.now(timezone.utc)
    # `expires_at` from the DB is tz-aware; defensive normalisation
    # in case a naive datetime ever slips through (Pydantic v2 strips
    # tz on some round-trips).
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (expires_at - now).total_seconds() > seconds


def _safe_json(response: httpx.Response) -> Optional[dict]:
    try:
        return response.json()
    except ValueError:
        return None


__all__ = ["GoogleAdsRestClient"]
