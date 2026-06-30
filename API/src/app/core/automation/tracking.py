"""Open + click tracking endpoints for outbound automation emails.

The :mod:`core.automation.tasks` ``deliver_run`` body rewrites
outbound email HTML in two ways:

  1. Appends an open-tracking ``<img src="…/track/open/{token}">``
     pixel. When the recipient's mail client renders the image, the
     hit lands here + we stamp ``opened_at`` on the run.
  2. Rewrites every ``<a href="…">`` so the URL points at
     ``…/track/click/{token}?u=<original-url>``. The click endpoint
     stamps ``clicked_at`` + 302s to the original URL.

Both endpoints are **public** (no auth) because mail clients can't
carry session cookies, but the ``token`` is an HMAC-signed
``f"{run_id}:{action}"`` so external actors can't fabricate hits
for arbitrary runs.

Token format: ``base64url(hmac_sha256(SECRET, f"{run_id}:{action}"))[:32]``.
The truncation keeps the URL compact; 32 hex chars = 128 bits of
entropy which is plenty against guessing.

Only the FIRST open + FIRST click are recorded — multi-event
tracking (opens-over-time, multiple-click attribution) is deferred
per the spec's "out of scope". The columns stay on the run row for
fast contact-timeline reads (no per-event join).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/automations/track", tags=["Automation Tracking"])


# 1×1 transparent GIF — what we serve for every open-pixel request,
# success or failure. Returning the same bytes either way keeps the
# tracking flow indistinguishable to a snooping bystander.
_TRANSPARENT_GIF: bytes = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


def _tracking_secret() -> bytes:
    """Read the HMAC key. Falls back to a process-local random key
    if unset — that mode is fine for local dev (tokens minted +
    verified within the same process); production deployments MUST
    set ``AUTOMATION_TRACKING_SECRET`` so tokens survive worker
    restarts."""
    secret = os.environ.get("AUTOMATION_TRACKING_SECRET")
    if secret:
        return secret.encode("utf-8")
    return _DEV_FALLBACK_KEY


# Stable for the process lifetime so dev-mode tokens minted in one
# request can be redeemed in the next.
_DEV_FALLBACK_KEY = os.urandom(32)


Action = Literal["open", "click"]


def mint_token(*, run_id: uuid.UUID, action: Action) -> str:
    """Generate the URL-safe HMAC token for a (run_id, action) pair.
    The renderer in :mod:`core.automation.tasks` calls this for
    each outbound email + bakes the token into the pixel/link URL.
    """
    payload = f"{run_id}:{action}".encode()
    digest = hmac.new(_tracking_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")[:32]


def verify_token(*, run_id: uuid.UUID, action: Action, token: str) -> bool:
    """Constant-time compare of the supplied token against the
    expected mint. Returns ``False`` on any input that isn't an
    exact match — never raises so the endpoint can return the
    silent 1×1 GIF / 410 without leaking signal."""
    expected = mint_token(run_id=run_id, action=action)
    try:
        return hmac.compare_digest(expected, token)
    except Exception:
        return False


# --- Open-pixel endpoint -------------------------------------------------


@router.get(
    "/open/{run_id}/{token}",
    include_in_schema=False,
)
async def track_open(run_id: uuid.UUID, token: str) -> Response:
    """Record the FIRST open for an automation run + return the 1×1
    GIF. Multiple opens collapse to one — ``opened_at`` is set only
    when the column is currently NULL."""
    if not verify_token(run_id=run_id, action="open", token=token):
        # Invalid token → return the GIF anyway. The recipient's
        # client doesn't care; a 4xx might let an active attacker
        # distinguish valid runs from invalid ones.
        return Response(content=_TRANSPARENT_GIF, media_type="image/gif")

    await _stamp_engagement(run_id=run_id, action="open")
    return Response(content=_TRANSPARENT_GIF, media_type="image/gif")


# --- Click-redirect endpoint --------------------------------------------


@router.get(
    "/click/{run_id}/{token}",
    include_in_schema=False,
)
async def track_click(
    run_id: uuid.UUID,
    token: str,
    u: str = Query(..., description="Original URL to redirect to"),
) -> Response:
    """Record the FIRST click for an automation run + 302 to the
    original URL. Bad tokens still redirect (so a forwarded mail
    doesn't break for the recipient) but skip the engagement
    stamp."""
    if not _is_safe_redirect_target(u):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_redirect_target",
        )
    if verify_token(run_id=run_id, action="click", token=token):
        await _stamp_engagement(run_id=run_id, action="click")
    return RedirectResponse(url=u, status_code=302)


# --- Helpers -------------------------------------------------------------


def _is_safe_redirect_target(url: str) -> bool:
    """Block obviously bad redirect targets (javascript:, data:, …).
    Only http / https URLs are allowed."""
    lower = (url or "").strip().lower()
    return lower.startswith("http://") or lower.startswith("https://")


async def _stamp_engagement(*, run_id: uuid.UUID, action: Action) -> None:
    """Set ``opened_at`` or ``clicked_at`` on the run row if not
    already set. Cross-tenant write (the row's own org_id supplies
    the tenant); we bypass the RequestContext check + go through a
    direct UPDATE so a stale public token doesn't need a tenant
    cookie to redeem."""
    from sqlalchemy import select as _select
    from sqlalchemy import update as _update

    from src.app.core.automation.models import AutomationRun
    from src.app.shared.db import async_session

    column = "opened_at" if action == "open" else "clicked_at"
    now = datetime.now(UTC)

    async with async_session() as session:
        run = (
            await session.execute(_select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            return
        # Only stamp once — the FIRST open / FIRST click wins.
        if getattr(run, column) is not None:
            return
        await session.execute(
            _update(AutomationRun).where(AutomationRun.id == run_id).values({column: now})
        )
        await session.commit()


def inject_tracking_pixel_and_links(
    *,
    run_id: uuid.UUID,
    html_body: str | None,
    public_base_url: str,
) -> str | None:
    """Rewrite outbound email HTML to embed the open-pixel + click
    redirects. Returns ``None`` when the input is ``None`` (the
    sender will skip the HTML part); the plain-text body stays
    unmodified.

    Implementation notes:
      * The pixel is appended as the LAST tag inside ``</body>`` so
        the rendered body's layout isn't perturbed; if no ``</body>``
        tag is present, the pixel is appended to the end of the
        string.
      * Link rewriting uses a narrow regex — full HTML parsing
        isn't justified at this layer (Gmail / Outlook render the
        raw href; query-string rewrites compose cleanly).
    """
    if html_body is None:
        return None

    import re
    from urllib.parse import quote

    open_token = mint_token(run_id=run_id, action="open")
    pixel_url = f"{public_base_url.rstrip('/')}/api/v1/automations/track/open/{run_id}/{open_token}"
    pixel_tag = (
        f'<img src="{pixel_url}" alt="" width="1" height="1" '
        'style="display:none;border:0;width:1px;height:1px"/>'
    )

    click_token = mint_token(run_id=run_id, action="click")
    click_prefix = (
        f"{public_base_url.rstrip('/')}/api/v1/automations/track/click/{run_id}/{click_token}?u="
    )

    def _rewrite_href(match: re.Match) -> str:
        original = match.group(2)
        # Skip mailto:, tel:, and anchors — only http(s) links get
        # rewritten.
        lower = original.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            return match.group(0)
        return f'{match.group(1)}="{click_prefix}{quote(original, safe="")}"'

    rewritten = re.sub(r'(href|HREF)="([^"]+)"', _rewrite_href, html_body)

    if "</body>" in rewritten:
        rewritten = rewritten.replace("</body>", f"{pixel_tag}</body>", 1)
    else:
        rewritten = f"{rewritten}{pixel_tag}"
    return rewritten


__all__ = [
    "inject_tracking_pixel_and_links",
    "mint_token",
    "router",
    "verify_token",
]
