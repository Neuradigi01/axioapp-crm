"""Reputation dashboard endpoint (Owner-only).

``GET /api/v1/reputation/dashboard`` returns one
:class:`EnvelopeReputationOut` per (org, envelope) — a platform-from
row (if any events have landed) plus one per verified own-domain that
has a reputation row. Also surfaces envelopes with no row yet as
"pristine" zeros so the frontend renders the card in a neutral state
before the first event.

Business logic lives in :mod:`.service.dashboard_service`; this
file is thin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.reputation.dashboard_service import list_reputation_for_org
from src.app.core.email.reputation.schemas import EnvelopeReputationOut
from src.app.core.users.models import User
from src.app.shared.db import get_db

# Owner-only — dashboard shows send-reputation state that a rep-role
# shouldn't be reading (an "am I about to get shed?" surface is a
# workspace-ownership concern, matches the sending-domains permission).
_DASHBOARD_PERM = "email.sending_domains.manage"


router = APIRouter(prefix="/reputation", tags=["Email Reputation"])


@router.get("/dashboard", response_model=list[EnvelopeReputationOut])
async def get_reputation_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(_DASHBOARD_PERM)),
) -> list[EnvelopeReputationOut]:
    """Return one card row per envelope the caller's org uses. Includes
    a synthetic ``platform_from`` row when no events have landed yet
    (so the UI has something to render) and one row per verified
    own-domain (whether or not it has any events)."""
    return await list_reputation_for_org(db, org_id=user.org_id)


__all__ = ["router"]
