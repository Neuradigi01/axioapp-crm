"""Shared OAuth scaffolding for the email-accounts track.

The Gmail (Step 2) and Microsoft Graph (Step 3) adapters each
register a provider with this module's registry at import time. The
shared service layer then dispatches `refresh()` calls by
`account.provider` without needing compile-time knowledge of either
adapter — consistent with the broader module-registry pattern (Rule
5/6 of the master prompt).

The registry holds a single instance per provider name. Re-registering
overwrites silently — used by tests to swap in mock providers.

`OAuthStateSigner` HMAC-signs the `state` parameter that round-trips
through the provider's consent screen, with a short TTL, to defeat
CSRF on the callback. Steps 2 + 3 call `issue_state(...)` before
redirecting and `verify_state(...)` inside the callback before
trusting the inbound `code`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Protocol

from config import JWT_SECRET_KEY


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Plaintext tokens just out of an OAuth exchange or refresh.

    Plaintext is the right shape for this dataclass — callers pass
    it straight into `service.upsert(...)` which encrypts before
    persisting. The lifetime of a `TokenSet` instance is bound to a
    single function call; it never lives on a model attribute.
    """

    access_token: str
    refresh_token: str | None
    expires_in_seconds: int | None
    scopes_granted: list[str]


class OAuthProvider(Protocol):
    """Provider-specific OAuth client interface. The Gmail and
    Microsoft adapters each implement one of these and register it
    via `register_provider(...)`.

    Steps 2 + 3 implement `authorize_url` + `exchange_code` +
    `refresh`. Step 1 only declares the protocol; nothing exercises
    these methods until those adapters land.
    """

    name: str

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Build the provider's hosted consent URL. The caller
        redirects the browser there; the user consents; the
        provider redirects back to `redirect_uri` with `code` +
        the same `state` echoed back."""
        ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> TokenSet:
        """POST `code` to the provider's token endpoint; return the
        plaintext token set. Caller passes this to
        `service.upsert(...)` to persist."""
        ...

    async def refresh(self, *, refresh_token: str) -> TokenSet:
        """Trade a refresh token for a fresh access token. Called
        by `service.refresh_if_expired(...)` when the cached access
        token is within 5 min of expiring."""
        ...


# Module-level registry. One instance per provider name.
_providers: dict[str, OAuthProvider] = {}


def register_provider(provider: OAuthProvider) -> None:
    """Steps 2 + 3 call this at import time. Re-registering the same
    name overwrites (used in tests to swap in mocks)."""
    _providers[provider.name] = provider


def get_provider(name: str) -> OAuthProvider | None:
    """Return the registered provider, or None. The caller decides
    how to handle the missing case — typically the OAuth callback
    raises 503 ("Provider not configured")."""
    return _providers.get(name)


def list_provider_names() -> list[str]:
    """Names of every registered provider. Used by the Settings UI
    in Step 9 to render Connect cards only for providers actually
    available in this deploy."""
    return sorted(_providers.keys())


def _clear_registry_for_tests() -> None:
    """Tests use this to wipe the registry between cases."""
    _providers.clear()


# --- OAuth state signing -------------------------------------------------


class OAuthStateError(RuntimeError):
    """Raised when an inbound `state` parameter on the OAuth
    callback fails HMAC verification, has expired, or carries a
    payload shape the callback didn't expect."""


@dataclass(frozen=True, slots=True)
class OAuthStatePayload:
    """Decoded state payload. Steps 2 + 3 stamp the requesting user
    + provider name + redirect intent at issue time; the callback
    reads them back after verification to know which user/org the
    callback belongs to (Postgres tenant context is empty during the
    callback — the request is not JWT-authenticated)."""

    user_id: str
    org_id: str
    provider: str
    issued_at: int
    nonce: str


_STATE_TTL_SECONDS = 600  # 10-minute consent window


def issue_state(*, user_id: str, org_id: str, provider: str) -> str:
    """Build an HMAC-signed `state` string for the OAuth redirect.
    The payload survives the round-trip through the provider's
    consent screen; the callback reads it via `verify_state`.

    Format: `<json-b64url>.<hmac-hex>`. The signing key is the same
    `JWT_SECRET_KEY` the rest of the auth stack uses — one fewer
    secret to rotate, and the state is no longer-lived than a JWT.
    """
    payload = {
        "u": user_id,
        "o": org_id,
        "p": provider,
        "t": int(time.time()),
        "n": secrets.token_urlsafe(16),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = _sign(body)
    # url-safe-b64 the body so it survives URL encoding cleanly.
    import base64

    body_b64 = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii")
    return f"{body_b64}.{sig}"


def verify_state(state: str) -> OAuthStatePayload:
    """Validate an inbound `state` from an OAuth callback.

    Raises `OAuthStateError` if the HMAC is invalid, the payload
    can't be parsed, or the state is older than `_STATE_TTL_SECONDS`.
    Step 2 + 3 callbacks call this BEFORE trusting any other inbound
    parameter — a state failure means the request is forged or
    stale and the callback must 400.
    """
    if not state or "." not in state:
        raise OAuthStateError("state missing or malformed")
    body_b64, sig = state.rsplit(".", 1)
    try:
        import base64

        body = base64.urlsafe_b64decode(body_b64.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise OAuthStateError("state body not decodable") from exc
    expected = _sign(body)
    # `compare_digest` defeats timing attacks against the HMAC check.
    if not hmac.compare_digest(expected, sig):
        raise OAuthStateError("state signature invalid")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OAuthStateError("state body not JSON") from exc
    issued_at = int(payload.get("t", 0))
    if issued_at <= 0 or time.time() - issued_at > _STATE_TTL_SECONDS:
        raise OAuthStateError("state expired")
    return OAuthStatePayload(
        user_id=str(payload["u"]),
        org_id=str(payload["o"]),
        provider=str(payload["p"]),
        issued_at=issued_at,
        nonce=str(payload["n"]),
    )


def _sign(body: str) -> str:
    key = (JWT_SECRET_KEY or "").encode("utf-8")
    if not key:
        # Refuse to issue/verify state without a real signing key —
        # better to fail loudly than to ship an unsigned state.
        raise OAuthStateError("JWT_SECRET_KEY is not configured; cannot sign OAuth state")
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


__all__ = [
    "OAuthProvider",
    "OAuthStateError",
    "OAuthStatePayload",
    "TokenSet",
    "get_provider",
    "issue_state",
    "list_provider_names",
    "register_provider",
    "verify_state",
]
