"""Reviews module — generic review aggregation + reply workflow.

Re-exports service entry points so other modules (Campaigns in
Phase 5.6) can hook into the reply / escalate flow without importing
FastAPI / Pydantic.
"""

from src.app.core.reviews.service import (
    create_review,
    delete_review,
    escalate_review,
    get_review,
    list_reviews,
    reply_to_review,
    stats,
    update_review,
)

__all__ = [
    "create_review",
    "delete_review",
    "escalate_review",
    "get_review",
    "list_reviews",
    "reply_to_review",
    "stats",
    "update_review",
]
