"""Audit-event helpers for entity CRUD writes.

:func:`log_entity_change` is the conventional entry point for the
"this entity just changed" audit events fired from service create /
update / delete paths. It's a thin keyword-only wrapper around
:func:`src.app.core.audit.log` that:

- enforces a uniform call shape across modules,
- documents required fields (``action``, ``entity_type``, ``entity_id``)
  while keeping ``before`` / ``after`` optional,
- gives Step 7 a single place to add automatic snapshotting later.

The wrapper does **not** derive the ``action`` string from
``entity_type``. The project's event-name conventions vary
(``contacts.created``, ``leads.scoring_rule.updated``,
``inventory.warehouse_created`` etc.), so the caller passes the full
dotted event name — bit-identical to the current
``audit.log("...", ...)`` contract — and the wrapper just forwards.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.app.core import audit


async def log_entity_change(
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Record a `<entity> changed` audit event.

    ``action`` is the full dotted event name (e.g. ``"contacts.created"``).
    Tenant / user / IP / UA context is resolved automatically from the
    active :class:`RequestContext` inside the audit service.
    """
    await audit.log(
        action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
    )
