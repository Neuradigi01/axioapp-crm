"""Generic pagination envelope for list endpoints.

Every offset-paginated list endpoint in `app.core` returns
``PaginatedResponse[ItemSchema]`` so the frontend sees the same
``items / total / page / size`` shape regardless of entity.

Endpoints that need cursor mode (e.g. ``LeadListResponse`` with
``next_cursor``) define their own envelope and do not use this generic.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
