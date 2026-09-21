"""Platform-from envelope construction for the email send cascade.

When an org has no verified own-domain and no connected mailbox, the
``resolve_send_envelope`` cascade returns a ``platform_from`` envelope:
the CRM sends on the org's behalf from ``org-<uuid>@<platform_domain>``
and receives replies at ``r-<reply_token>@<inbound_domain>``. This
helper composes those addresses and resolves the ``reply_token``.

Sibling to ``adapters/email.py`` — factored out so that (a) the send
cascade wiring in Step 5b stays a narrow ``if envelope_type ==
'platform_from': ...`` branch, and (b) tests can pin the envelope
shape independently from the actual send dispatch.

Reply-token selection strategy:

  1. If the org already has an active ``smtp_reply_capture`` endpoint
     (some SMTP sender was set up with reply-capture on), reuse its
     ``reply_token`` — replies to platform-from sends land in the same
     inbox as replies to their SMTP-sender sends.

  2. Otherwise, create an org-wide ``platform_reply_capture`` endpoint
     with a fresh ``reply_token`` at first use. The endpoint is tied
     to no specific sender (``smtp_sender_id`` / ``oauth_account_id``
     / ``domain_id`` all NULL) — it exists solely to give
     platform-from sends an inbound landing point.

Case #10 from the README (first platform-from send emits an in-app
"you're on platform sending" notification) is wired into the send
path itself in Step 5b, not here — this helper is transport-address
composition only.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.channel_endpoints import data_access as endpoints_da
from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
    ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
    ChannelEndpoint,
    EmailEndpointDetails,
)

logger = logging.getLogger(__name__)


# Notification type key + payload marker for the first-use in-app
# nudge. Exported so :mod:`adapters.email` (Step 5b) fires them from
# the send path without redeclaring the strings.
FIRST_USE_NOTIFICATION_TYPE = "email.first_platform_from_send"
FIRST_USE_NOTIFICATION_KEY = "first_platform_from_send"


@dataclass(frozen=True, slots=True)
class PlatformEnvelope:
    """The three transport addresses a platform-from Mailgun send needs.

    * ``from_address`` — ``org-<uuid>@<platform_domain>``. The RFC 5322
      ``From`` header value. Local-part uses the full UUID so it
      neither leaks a sequential id nor enables directory enumeration.
    * ``reply_to`` — ``r-<reply_token>@<inbound_domain>``. The RFC 5322
      ``Reply-To`` header value. Mailgun-inbound / Track 3's reply-
      capture routes match ``r-<token>`` back to the endpoint row.
    * ``dispatch_domain`` — the domain to POST the message.mime to
      (``POST /v3/<dispatch_domain>/messages.mime``). Equal to
      ``platform_domain``; kept as its own field so the caller
      doesn't have to re-parse the From address.
    """

    from_address: str
    reply_to: str
    dispatch_domain: str


def _platform_sending_domain() -> str:
    """Resolve ``EMAIL_PLATFORM_SENDING_DOMAIN`` at call time.

    Read-at-call (not read-at-import) so tests can monkey-patch
    ``os.environ`` per-test without a module reload.
    """
    value = os.getenv("EMAIL_PLATFORM_SENDING_DOMAIN", "").strip()
    return value


def _inbound_domain(*, fallback_to_platform: str | None = None) -> str:
    """Resolve ``INBOUND_EMAIL_DOMAIN`` at call time.

    Falls back to ``fallback_to_platform`` when the inbound domain
    isn't set — deployments that share one Mailgun domain for both
    directions (the common single-tenant setup) keep working.
    """
    value = os.getenv("INBOUND_EMAIL_DOMAIN", "").strip()
    if value:
        return value
    if fallback_to_platform is not None:
        return fallback_to_platform
    return ""


def build_platform_envelope(
    *,
    org_id: uuid.UUID,
    reply_token: str,
    platform_domain: str | None = None,
    inbound_domain: str | None = None,
) -> PlatformEnvelope:
    """Compose the platform-from transport envelope.

    ``platform_domain`` / ``inbound_domain`` fall through to
    ``EMAIL_PLATFORM_SENDING_DOMAIN`` / ``INBOUND_EMAIL_DOMAIN`` env
    vars when None so the caller can pass explicit values in tests
    without touching ``os.environ``.

    Raises :class:`PlatformFromNotConfiguredError` when no platform
    sending domain resolves — the caller (Step 5b) surfaces this as
    ``SendNotConfiguredError`` at the send cascade's tail.
    """
    resolved_platform = platform_domain or _platform_sending_domain()
    if not resolved_platform:
        raise PlatformFromNotConfiguredError(
            "EMAIL_PLATFORM_SENDING_DOMAIN is not configured for this deploy"
        )
    resolved_inbound = inbound_domain or _inbound_domain(fallback_to_platform=resolved_platform)
    return PlatformEnvelope(
        from_address=f"org-{org_id}@{resolved_platform}",
        reply_to=f"r-{reply_token}@{resolved_inbound}",
        dispatch_domain=resolved_platform,
    )


class PlatformFromNotConfiguredError(Exception):
    """Raised by :func:`build_platform_envelope` when the deploy has
    no ``EMAIL_PLATFORM_SENDING_DOMAIN``. The send cascade maps this
    to :class:`core.email_sender_setup.service.SendNotConfiguredError`
    at the router edge."""


async def resolve_or_create_platform_reply_token(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> tuple[str, bool]:
    """Return ``(reply_token, created_endpoint)`` for platform-from sends.

    Preference order:

      1. Any active ``smtp_reply_capture`` endpoint the org already has
         — its ``reply_token`` is reused so all inbound-to-CRM traffic
         for this org (platform-from + SMTP-sender captures) shares
         one address space.
      2. An existing active ``platform_reply_capture`` endpoint from
         a prior first-use call for this org.
      3. Fresh ``platform_reply_capture`` endpoint + details row
         created here; token generated via the same
         :func:`endpoints_da._generate_token` used for the
         ``smtp_reply_capture`` flow so collision handling and length
         are identical.

    Caller commits — this helper only stages the INSERT (the DAL
    ``add_endpoint`` / ``add_details`` calls flush inside their retry
    loops but don't commit).

    ``created_endpoint`` is True iff a new ``platform_reply_capture``
    row was staged in this call — Step 5b uses this signal to fire
    the first-use "you're on platform sending" in-app notification.
    """
    # Preference 1: reuse an SMTP reply-capture token if one exists.
    smtp_rows = await endpoints_da.find_active_for_org(
        session,
        org_id=org_id,
        endpoint_type=ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
    )
    for _endpoint, details in smtp_rows:
        if details is not None and details.reply_token:
            return details.reply_token, False

    # Preference 2: reuse a prior platform_reply_capture endpoint.
    platform_rows = await endpoints_da.find_active_for_org(
        session,
        org_id=org_id,
        endpoint_type=ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
    )
    for _endpoint, details in platform_rows:
        if details is not None and details.reply_token:
            return details.reply_token, False

    # Preference 3: create one.
    endpoint, details = await _create_platform_reply_capture(session, org_id=org_id)
    logger.info(
        "email_platform_from.created_endpoint org=%s endpoint=%s token=%s",
        org_id,
        endpoint.id,
        # First 4 chars only — enough for correlation, not enough to
        # replay a reply. Full token stays in the DB.
        (details.reply_token or "")[:4] + "…",
    )
    return details.reply_token or "", True


async def _create_platform_reply_capture(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> tuple[ChannelEndpoint, EmailEndpointDetails]:
    """Stage a new ``platform_reply_capture`` endpoint + details row.

    Mirrors :func:`endpoints_da.create_smtp_reply_capture` but with
    all FK columns NULL — this endpoint is org-wide, not tied to a
    specific SMTP sender or OAuth account. Retry loop copes with the
    (astronomically unlikely) reply-token UNIQUE collision.

    Not exposed as a public DAL function because
    ``platform_reply_capture`` is only ever created inside the send
    cascade — external callers claim domains or connect mailboxes,
    they don't manually mint platform endpoints. Keeps the DAL
    surface narrow.
    """
    from sqlalchemy.exc import IntegrityError

    for _ in range(endpoints_da._TOKEN_COLLISION_MAX_RETRIES):
        token = endpoints_da._generate_token()
        endpoint = ChannelEndpoint(
            org_id=org_id,
            channel=CHANNEL_EMAIL,
            endpoint_type=ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
            label="Platform reply capture",
        )
        endpoints_da.add_endpoint(session, endpoint)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue

        details = EmailEndpointDetails(
            endpoint_id=endpoint.id,
            org_id=org_id,
            reply_token=token,
        )
        endpoints_da.add_details(session, details)
        try:
            await session.flush()
            return endpoint, details
        except IntegrityError:
            await session.rollback()
            continue

    raise RuntimeError(
        "email_platform_from._create_platform_reply_capture: token "
        f"collision retry limit exceeded "
        f"({endpoints_da._TOKEN_COLLISION_MAX_RETRIES})"
    )


async def already_notified_first_platform_from(session: AsyncSession, *, org_id: uuid.UUID) -> bool:
    """Defensive idempotency check for the first-use in-app nudge.

    Notification rows don't carry a
    ``UNIQUE(org_id, type, payload_key)`` constraint today; a DB-side
    unique would require a migration + a partial index. In the
    meantime this helper is the belt: Step 5b's ``send_email`` calls
    it before firing :func:`notifications.notify` and skips the notify
    when it returns True.

    Uses raw SQL on the notifications table so the DAL doesn't need a
    ``notifications`` cross-module import — Rule 5 (Router → Service
    → DAL) is preserved because the caller is a service-layer helper.
    """
    # Late import to avoid a hard adapter → notifications cycle at
    # module load — this helper is imported by the email adapter,
    # and notifications is a peer module.
    from src.app.core.notifications.models import Notification

    stmt = (
        select(Notification.id)
        .where(Notification.org_id == org_id)
        .where(Notification.type == FIRST_USE_NOTIFICATION_TYPE)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.first() is not None


__all__ = [
    "FIRST_USE_NOTIFICATION_KEY",
    "FIRST_USE_NOTIFICATION_TYPE",
    "PlatformEnvelope",
    "PlatformFromNotConfiguredError",
    "already_notified_first_platform_from",
    "build_platform_envelope",
    "resolve_or_create_platform_reply_token",
]
