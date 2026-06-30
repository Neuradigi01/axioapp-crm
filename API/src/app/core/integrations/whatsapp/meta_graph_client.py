"""Typed async wrapper for the five Meta Graph API calls the
Embedded Signup orchestration needs (Step 2).

Why this lives separately from the existing `connect.py`'s
`_validate_with_meta`: the manual-connect path only ever needed one
read (`GET /{phone_id}?fields=...`). Embedded Signup needs a small
*choreography* — exchange the code for a token, fetch the WABA, list
phones, subscribe the app, register the phone for Cloud API — and
those calls all share the same HTTP-client + retry + error-mapping
plumbing. Keeping the choreography in `embedded_signup.py` and the
plumbing here gives the orchestration something testable to stub out.

Every method maps non-2xx Meta responses to a typed `MetaGraphError`
that carries the HTTP status + the friendly user-facing message the
router will surface. The orchestration never sees raw httpx errors.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


HttpClientFactory = Callable[[], httpx.AsyncClient]


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30.0)


# --- typed result objects -------------------------------------------------


@dataclass(frozen=True, slots=True)
class WabaInfo:
    """Subset of `GET /{waba_id}?fields=...` we use during ES persist."""

    id: str
    name: str | None
    verified_name: str | None
    timezone_offset_min: int | None


@dataclass(frozen=True, slots=True)
class PhoneInfo:
    """Subset of `GET /{phone_id}?fields=...` we use during ES persist."""

    id: str
    display_phone_number: str
    verified_name: str | None
    quality_rating: str | None
    code_verification_status: str | None
    messaging_limit_tier: str | None


# --- typed error -----------------------------------------------------------


class MetaGraphError(Exception):
    """One typed exception for every Meta Graph API failure during ES.

    `http_status` is the status code the router will raise on the
    caller's behalf — already pre-mapped per the step spec:
    400 (code-exchange rejection), 403 (subscribe / register
    permission denied), 503 (webhook not yet verified), 502 (other).
    `user_message` is the operator-facing string the Settings UI
    shows in the toast — pre-translated for clarity.
    `meta_code` is the raw Meta error code when available, kept for
    audit-log forensics; never bubbled to the UI."""

    def __init__(
        self,
        *,
        http_status: int,
        user_message: str,
        meta_code: int | None = None,
        meta_subcode: int | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(user_message)
        self.http_status = http_status
        self.user_message = user_message
        self.meta_code = meta_code
        self.meta_subcode = meta_subcode
        self.raw = raw


# --- error mapping ---------------------------------------------------------


def _extract_meta_error(
    response: httpx.Response,
) -> tuple[int | None, int | None, str, dict[str, Any] | None]:
    """Pull `(code, subcode, message, raw_error)` out of Meta's error
    envelope, falling back to the raw text + status when the body
    isn't JSON."""
    try:
        payload = response.json()
    except ValueError:
        return None, None, (f"HTTP {response.status_code}: {response.text[:200]}"), None
    if not isinstance(payload, dict):
        return None, None, f"HTTP {response.status_code}: {payload!r}", None
    err = payload.get("error")
    if not isinstance(err, dict):
        return None, None, (f"HTTP {response.status_code}: {response.text[:200]}"), None
    code = err.get("code") if isinstance(err.get("code"), int) else None
    subcode = err.get("error_subcode") if isinstance(err.get("error_subcode"), int) else None
    message = (
        err.get("message")
        if isinstance(err.get("message"), str)
        else (f"HTTP {response.status_code}")
    )
    return code, subcode, message, err


def _classify(
    *,
    response: httpx.Response,
    stage: str,
) -> MetaGraphError:
    """Translate a non-2xx response into a MetaGraphError with the
    correct user-facing http_status + message per the step spec.

    `stage` discriminates which orchestration step failed:
      - `code_exchange`: 400 from Meta → 400 to caller
      - `subscribe_apps` / `register_phone`: 403 → 403 to caller
      - `webhook_not_verified`: surfaced by Meta as a 400 on the
        subscribe call when the webhook URL isn't verified yet.
      - anything else → 502.
    """
    code, subcode, message, raw = _extract_meta_error(response)
    status = response.status_code

    # Webhook-not-verified surfaces from Meta as 400 with a specific
    # message — sniff the text and 503 it so the operator knows it's a
    # config issue, not a credential issue.
    if (
        stage == "subscribe_apps"
        and "webhook" in message.lower()
        and ("not verified" in message.lower() or "callback" in message.lower())
    ):
        return MetaGraphError(
            http_status=503,
            user_message=(
                "Webhook setup incomplete — see Step 1 (callback URL not yet verified at Meta)."
            ),
            meta_code=code,
            meta_subcode=subcode,
            raw=raw,
        )

    if stage == "code_exchange" and status in (400, 401, 403):
        return MetaGraphError(
            http_status=400,
            user_message=("Embedded Signup session expired — please retry."),
            meta_code=code,
            meta_subcode=subcode,
            raw=raw,
        )

    if stage in ("subscribe_apps", "register_phone") and status == 403:
        return MetaGraphError(
            http_status=403,
            user_message=("Account not approved for management — contact support."),
            meta_code=code,
            meta_subcode=subcode,
            raw=raw,
        )

    logger.warning(
        "meta_graph_error stage=%s status=%s code=%s message=%s",
        stage,
        status,
        code,
        message,
    )
    return MetaGraphError(
        http_status=502,
        user_message=f"Meta API error during {stage}: {message}",
        meta_code=code,
        meta_subcode=subcode,
        raw=raw,
    )


# --- client ---------------------------------------------------------------


class MetaGraphClient:
    """Thin async wrapper over the five Graph endpoints ES needs.

    One instance per orchestration run — cheap to build; holds no
    state beyond the API version + app credentials. HTTP client is
    constructed fresh per call so we never carry connections across
    process restarts."""

    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        *,
        api_version: str,
        app_id: str,
        app_secret: str,
        http_client_factory: HttpClientFactory = _default_http_client_factory,
    ) -> None:
        self._api_version = api_version
        self._app_id = app_id
        self._app_secret = app_secret
        self._factory = http_client_factory

    def _url(self, path: str) -> str:
        return f"{self.BASE_URL}/{self._api_version}{path}"

    async def _request(
        self,
        *,
        method: str,
        url: str,
        stage: str,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """One-shot retry on 5xx, then bubble. Maps non-2xx to typed
        MetaGraphError via the stage-specific classifier."""
        last_response: httpx.Response | None = None
        for attempt in (1, 2):
            async with self._factory() as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                )
            last_response = response
            if response.status_code < 500:
                break
            # 5xx → one retry after a tiny back-off. Meta rarely 5xx
            # but if it does, a single retry burns very little budget.
            if attempt == 1:
                await asyncio.sleep(0.5)
        assert last_response is not None
        if last_response.status_code >= 400:
            raise _classify(response=last_response, stage=stage)
        try:
            body = last_response.json()
        except ValueError:
            raise MetaGraphError(
                http_status=502,
                user_message=(f"Meta API returned a non-JSON body during {stage}."),
            )
        if not isinstance(body, dict):
            raise MetaGraphError(
                http_status=502,
                user_message=(f"Meta API returned an unexpected shape during {stage}."),
            )
        return body

    # ----- 1. code → long-lived token --------------------------------------

    async def exchange_code(self, code: str) -> str:
        """`GET /oauth/access_token?client_id=...&client_secret=...&code=...`.

        Meta returns a long-lived business-system-user token for ES
        flows in v19.0+, so no separate `fb_exchange_token` step is
        needed."""
        body = await self._request(
            method="GET",
            url=self._url("/oauth/access_token"),
            stage="code_exchange",
            params={
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "code": code,
            },
        )
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise MetaGraphError(
                http_status=502,
                user_message=("Meta did not return an access token — please retry."),
                raw=body,
            )
        return token

    # ----- 1a. extract Meta user_id from the exchanged token --------------

    async def debug_token(self, token: str) -> str | None:
        """Resolve the Meta-side user identity behind ``token``.

        Used by the ES orchestration to capture ``Integration.meta_user_id``
        for Step 4's Data Deletion Callback. Returns ``None`` (not a
        typed error) when Meta omits the field — the callback will
        simply find no matching integration row, which is the safe
        default. Callers MUST NOT block the connect flow on this
        lookup."""
        try:
            body = await self._request(
                method="GET",
                url=self._url("/debug_token"),
                stage="debug_token",
                params={
                    "input_token": token,
                    # App access token format: <app_id>|<app_secret>
                    "access_token": f"{self._app_id}|{self._app_secret}",
                },
            )
        except MetaGraphError as exc:
            logger.warning(
                "debug_token call failed (status=%s): %s",
                exc.http_status,
                exc.user_message,
            )
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        user_id = data.get("user_id")
        return str(user_id) if isinstance(user_id, str) and user_id else None

    # ----- 2. fetch WABA details -------------------------------------------

    async def get_waba(self, *, waba_id: str, token: str) -> WabaInfo:
        body = await self._request(
            method="GET",
            url=self._url(f"/{waba_id}"),
            stage="get_waba",
            params={
                "fields": "id,name,timezone_offset_min,verified_name",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        return WabaInfo(
            id=str(body.get("id") or waba_id),
            name=(str(body["name"]) if isinstance(body.get("name"), str) else None),
            verified_name=(
                str(body["verified_name"]) if isinstance(body.get("verified_name"), str) else None
            ),
            timezone_offset_min=(
                int(body["timezone_offset_min"])
                if isinstance(body.get("timezone_offset_min"), int)
                else None
            ),
        )

    # ----- 3. fetch phone-number details -----------------------------------

    async def get_phone_number(self, *, phone_id: str, token: str) -> PhoneInfo:
        body = await self._request(
            method="GET",
            url=self._url(f"/{phone_id}"),
            stage="get_phone_number",
            params={
                "fields": (
                    "id,display_phone_number,verified_name,quality_rating,"
                    "code_verification_status,messaging_limit_tier"
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        return _phone_from_payload(body, fallback_id=phone_id)

    # ----- 4. list phone numbers on a WABA ---------------------------------

    async def list_phone_numbers(self, *, waba_id: str, token: str) -> list[PhoneInfo]:
        body = await self._request(
            method="GET",
            url=self._url(f"/{waba_id}/phone_numbers"),
            stage="list_phone_numbers",
            params={
                "fields": (
                    "id,display_phone_number,verified_name,quality_rating,"
                    "code_verification_status,messaging_limit_tier"
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        raw = body.get("data")
        if not isinstance(raw, list):
            return []
        out: list[PhoneInfo] = []
        for entry in raw:
            if isinstance(entry, dict):
                out.append(_phone_from_payload(entry, fallback_id=""))
        return out

    # ----- 5. subscribe the app to the WABA --------------------------------

    async def subscribe_app_to_waba(self, *, waba_id: str, token: str) -> None:
        await self._request(
            method="POST",
            url=self._url(f"/{waba_id}/subscribed_apps"),
            stage="subscribe_apps",
            headers={"Authorization": f"Bearer {token}"},
        )

    # ----- 6. register the phone number for Cloud API ----------------------

    async def register_phone_number(self, *, phone_id: str, token: str, pin: str) -> None:
        await self._request(
            method="POST",
            url=self._url(f"/{phone_id}/register"),
            stage="register_phone",
            data={"messaging_product": "whatsapp", "pin": pin},
            headers={"Authorization": f"Bearer {token}"},
        )

    # ----- 7. submit a draft template for Meta approval -------------------
    # (whatsapp-platform-upgrade Step 8)

    async def submit_template(
        self,
        *,
        waba_id: str,
        token: str,
        name: str,
        language: str,
        category: str,
        components: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST a new template draft to ``/{waba_id}/message_templates``.

        Meta validates synchronously: schema errors come back as 400
        with a specific reason (header too long, mixed buttons, etc.).
        On success Meta returns ``{id, status, category}`` where
        ``id`` is the template's permanent Meta-side identifier and
        ``status`` is the initial value (typically ``PENDING``).
        Returns the parsed body for the caller to persist."""
        import json

        body = await self._request(
            method="POST",
            url=self._url(f"/{waba_id}/message_templates"),
            stage="submit_template",
            data={
                "name": name,
                "language": language,
                "category": category,
                "components": json.dumps(components),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        return body

    # ----- 8a. fetch a template's current status from Meta ---------------
    # (tasks/template-library Step 14)

    async def get_message_template(
        self,
        *,
        token: str,
        meta_template_id: str,
    ) -> dict[str, Any]:
        """``GET /{meta_template_id}?fields=status,rejected_reason,category,language,name``.

        Used by the central template library's status-sync path
        (hourly Celery sweep + manual "Refresh status" button). The
        node-id endpoint works on the template id directly — no need
        to scope to ``/{waba_id}/message_templates``. Meta returns
        ``status`` (APPROVED / REJECTED / PENDING / PAUSED /
        DISABLED), an optional ``rejected_reason``, plus the
        identifying ``name`` + ``language`` for the caller to confirm
        the right row is being updated.

        Wrapped errors are typed as :class:`MetaGraphError` — caller
        bubbles up to the operator verbatim.
        """
        return await self._request(
            method="GET",
            url=self._url(f"/{meta_template_id}"),
            stage="get_message_template",
            params={
                "fields": "status,rejected_reason,category,language,name",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    # ----- 9. delete a template (by name) from Meta ----------------------

    async def delete_template(
        self,
        *,
        waba_id: str,
        token: str,
        name: str,
        meta_template_id: str | None = None,
    ) -> None:
        """``DELETE /{waba_id}/message_templates?name=...``.

        Meta deletes ALL languages of a template name unless an
        ``hsm_id`` is supplied. We pass ``hsm_id=meta_template_id`` so
        the delete is scoped to the exact row the operator hit Delete
        on — sibling language rows survive. Idempotent: Meta returns
        success if the row is already gone."""
        params: dict[str, str] = {"name": name}
        if meta_template_id:
            params["hsm_id"] = meta_template_id
        await self._request(
            method="DELETE",
            url=self._url(f"/{waba_id}/message_templates"),
            stage="delete_template",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )


def _phone_from_payload(payload: dict[str, Any], *, fallback_id: str) -> PhoneInfo:
    """Map one phone-number Graph entry → typed `PhoneInfo`."""
    return PhoneInfo(
        id=str(payload.get("id") or fallback_id),
        display_phone_number=str(payload.get("display_phone_number") or ""),
        verified_name=(
            str(payload["verified_name"]) if isinstance(payload.get("verified_name"), str) else None
        ),
        quality_rating=(
            str(payload["quality_rating"])
            if isinstance(payload.get("quality_rating"), str)
            else None
        ),
        code_verification_status=(
            str(payload["code_verification_status"])
            if isinstance(payload.get("code_verification_status"), str)
            else None
        ),
        messaging_limit_tier=(
            str(payload["messaging_limit_tier"])
            if isinstance(payload.get("messaging_limit_tier"), str)
            else None
        ),
    )


__all__ = [
    "HttpClientFactory",
    "MetaGraphClient",
    "MetaGraphError",
    "PhoneInfo",
    "WabaInfo",
]
