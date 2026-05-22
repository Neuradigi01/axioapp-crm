"""Enumerate every CRM field a bulk-import row can map to.

The output drives:

  - `/leads/import/targets` (frontend dropdown options);
  - `presets.create_preset` server-side mapping validation.

The standard-target list here is the **same whitelist** that
`service._ALLOWED_STANDARD_TARGETS` enforces — they must stay aligned.
Each entry carries the human label, the field-type hint (so the
mapping UI can pick the right icon and warn on type mismatches), and
the backend-required flag (so the UI marks mandatory targets).

We intentionally do NOT pull this list from `core.standard_fields` —
that registry is about which DB columns are exposed for *user
overrides* (label / required / hidden customisation), not "what can
a bulk import write to". The two sets overlap but aren't identical
(`contact.notes` is writable but not overridable). Treating those as
the same surface would force one to grow the other unnecessarily.

Custom fields come from `custom_field_definitions` and surface as
`custom_data.<field_key>` targets, scoped to the active org.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.leads.imports.schemas import MappingTarget


@dataclass(frozen=True, slots=True)
class _StandardTarget:
    key: str
    label: str
    field_type: str
    required: bool


# Aligned 1:1 with `service._ALLOWED_STANDARD_TARGETS`. Add/remove
# entries in both places together — `_REQUIRED_TARGETS` in service.py
# is the matching source of truth for the `required` flag.
_STANDARD_TARGETS: Sequence[_StandardTarget] = (
    _StandardTarget("contact.full_name", "Full name", "text", required=True),
    _StandardTarget("contact.phone", "Phone", "tel", required=False),
    _StandardTarget("contact.email", "Email", "email", required=False),
    _StandardTarget("contact.source", "Source", "text", required=False),
    _StandardTarget("contact.notes", "Notes", "textarea", required=False),
    _StandardTarget(
        "lead.pipeline_stage", "Pipeline stage", "select", required=False
    ),
    _StandardTarget("lead.budget", "Budget", "currency", required=False),
    _StandardTarget(
        "lead.expected_close_date", "Expected close date", "date", required=False
    ),
)


async def list_targets(session: AsyncSession) -> list[MappingTarget]:
    """Build the full target list for the active org.

    The tenant ORM filter scopes `custom_field_definitions` reads to
    the active org automatically.
    """
    out: list[MappingTarget] = [
        MappingTarget(
            key=t.key,
            label=t.label,
            field_type=t.field_type,
            required=t.required,
            custom=False,
        )
        for t in _STANDARD_TARGETS
    ]

    rows = (
        await session.execute(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.entity_type.in_(("contact", "lead"))
            )
        )
    ).scalars().all()
    for row in rows:
        out.append(
            MappingTarget(
                key=f"custom_data.{row.field_key}",
                label=row.field_label,
                field_type=row.field_type.value,
                required=bool(row.is_required),
                custom=True,
            )
        )

    return out


async def list_target_keys(session: AsyncSession) -> set[str]:
    """Convenience helper for service-layer validation — just the
    string keys, no labels/types."""
    return {t.key for t in await list_targets(session)}


__all__ = ["list_target_keys", "list_targets"]
