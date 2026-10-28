"""Shared Pydantic schemas used across `app.core` and `app.packs`.

Anything generic enough to be reused by more than one module — pagination
envelopes, common request/response shapes — lives here.
"""

from src.app.shared.schemas.base import ORMModel, TimestampedOrgScopedOut
from src.app.shared.schemas.bulk_actions import (
    BulkAddTag,
    BulkAddTagResult,
    BulkDelete,
    BulkDeleteResult,
    BulkReassign,
    BulkReassignResult,
)
from src.app.shared.schemas.pagination import PaginatedResponse

__all__ = [
    "BulkAddTag",
    "BulkAddTagResult",
    "BulkDelete",
    "BulkDeleteResult",
    "BulkReassign",
    "BulkReassignResult",
    "ORMModel",
    "PaginatedResponse",
    "TimestampedOrgScopedOut",
]
