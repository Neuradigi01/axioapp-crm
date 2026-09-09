"""Catalog module — string enum for the publish state machine.

Stored as plain ``VARCHAR`` (no Postgres ENUM type) so adding a new
lifecycle state is a Python one-liner rather than an
``ALTER TYPE ... ADD VALUE`` migration. The service layer validates
every write against ``CatalogStatus``; the DAL treats the column as an
opaque string.

State machine (mirrors real-estate ``PropertyStatus`` minus the
terminal ``sold`` — a catalog product isn't a one-off asset)::

    draft ─┬─▶ published ─┬─▶ unpublished ──▶ published
           │              └─▶ archived
           └─▶ archived ──▶ draft

Publishing requires at least one image (primary cover OR gallery).
"""

from __future__ import annotations

import enum


class CatalogStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    unpublished = "unpublished"
    archived = "archived"


# Transitions allowed by the service layer. Kept alongside the enum so
# ``service.py`` and ``router.py`` can both consult a single source of
# truth. Values missing from a source key set are terminal.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    CatalogStatus.draft.value: {
        CatalogStatus.published.value,
        CatalogStatus.archived.value,
    },
    CatalogStatus.published.value: {
        CatalogStatus.unpublished.value,
        CatalogStatus.archived.value,
    },
    CatalogStatus.unpublished.value: {
        CatalogStatus.published.value,
        CatalogStatus.archived.value,
    },
    CatalogStatus.archived.value: {
        CatalogStatus.draft.value,
    },
}


__all__ = ["ALLOWED_TRANSITIONS", "CatalogStatus"]
