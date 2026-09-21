"""Response schemas for the reputation-dashboard endpoint.

One row per (org, envelope). Own-domain rows carry the domain string
so the frontend card renders the human-readable label without a
second lookup. Rates are pre-computed on the server so the client
doesn't have to guard the ``delivered == 0`` divide-by-zero.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EnvelopeReputationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    envelope_type: str
    domain_id: uuid.UUID | None
    domain_string: str | None
    warmup_stage: int
    stage_cap: int
    next_stage_cap: int
    stage_progress_pct: float
    daily_sent: int
    daily_cap: int
    delivered_24h: int
    bounced_24h: int
    complained_24h: int
    unsubscribed_24h: int
    complaint_rate: float
    bounce_rate: float
    reputation_state: str
    blocked_until: datetime | None


__all__ = ["EnvelopeReputationOut"]
