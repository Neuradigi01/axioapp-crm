"""Campaigns engine — channel-agnostic marketing/transactional sends.

Re-exports the service entry points so other modules (e.g. the
reviews auto-request hook in Phase 5.11) can enqueue a campaign
without importing FastAPI/Pydantic types.
"""
from src.app.core.campaigns.service import (
    create_campaign,
    delete_campaign,
    dispatch_chunk,
    enqueue,
    get_campaign,
    list_campaigns,
    resolve_audience,
    stats,
    update_campaign,
)

__all__ = [
    "create_campaign",
    "delete_campaign",
    "dispatch_chunk",
    "enqueue",
    "get_campaign",
    "list_campaigns",
    "resolve_audience",
    "stats",
    "update_campaign",
]
