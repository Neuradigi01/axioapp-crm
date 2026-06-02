"""Shared Pydantic schemas used across `app.core` and `app.packs`.

Anything generic enough to be reused by more than one module — pagination
envelopes, common request/response shapes — lives here.
"""

from src.app.shared.schemas.base import ORMModel
from src.app.shared.schemas.pagination import PaginatedResponse

__all__ = ["ORMModel", "PaginatedResponse"]
