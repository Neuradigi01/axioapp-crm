"""Variable-picker source for the chatbot builder.

Returns the categorised list of variables an operator can drop into
message bodies (``{{contact.first_name}}``), Ask-* question prompts,
API-request URLs, and similar interpolated fields.

Two entry points:

  * :func:`list_variables` — org-wide list. Composes hardcoded standard
    fields (Contact, Lead, Runtime) with the org's non-hidden custom
    fields for each entity. Consumed by the frontend
    ``<variable-picker>`` component and the canvas-side Variables panel.

Session variables (``answers.<node_id>``) are per-bot and per-graph, so
the frontend computes them locally from the current graph's Ask-*
nodes rather than round-tripping through this endpoint.

Runtime resolution today (see
:func:`core.chatbots.channel_bridge.render_variables`) covers:

  * ``contact.<field>`` — full_name, first_name, last_name, email, phone
  * ``run.<field>``     — channel, contact_id, conversation_id, last_inbound_text
  * ``answers.<node_id>`` — output of upstream Ask-* nodes

Unknown scopes (``lead.*`` / ``contact.custom.*``) currently render as
an empty string; the picker surfaces them anyway so operators can wire
flows in anticipation of runtime coverage. Extending the renderer is a
separate track — the picker's presence does not create a regression
(empty-string fallback matches existing behaviour for any bad path).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import data_access as _dal

# Custom-field keys are constrained the same way as save_target_registry
# (``^[a-z0-9_]{1,40}$``) so we don't surface legacy keys that would
# refuse to round-trip through the save-target validator.
_CUSTOM_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")


@dataclass(frozen=True, slots=True)
class Variable:
    """One entry in a picker group. ``path`` is what gets inserted
    verbatim into ``{{...}}`` at the cursor position."""

    path: str
    label: str
    description: str | None = None
    sample: str | None = None


@dataclass(frozen=True, slots=True)
class VariableGroup:
    """A labeled bucket of related variables. The frontend renders one
    collapsible section per group in the side panel + one option-group
    in the picker dropdown."""

    key: str
    label: str
    variables: list[Variable]


# --- Hardcoded standard-field lists --------------------------------------
#
# Contact / Runtime scopes are pinned in code because they mirror what
# ``channel_bridge.render_variables`` actually resolves at runtime.
# Lead scope is aspirational — see module docstring.

_CONTACT_STANDARD: tuple[Variable, ...] = (
    Variable(
        path="contact.full_name",
        label="Full name",
        description="Contact's full display name.",
        sample="Jane Smith",
    ),
    Variable(
        path="contact.first_name",
        label="First name",
        description="First word of the contact's full name.",
        sample="Jane",
    ),
    Variable(
        path="contact.last_name",
        label="Last name",
        description="Remainder of the full name after the first word.",
        sample="Smith",
    ),
    Variable(
        path="contact.email",
        label="Email",
        description="Primary email address.",
        sample="jane@example.com",
    ),
    Variable(
        path="contact.phone",
        label="Phone",
        description="Primary phone number in E.164 format.",
        sample="+14155551234",
    ),
)

_LEAD_STANDARD: tuple[Variable, ...] = (
    Variable(path="lead.status", label="Status", description="active / won / lost."),
    Variable(path="lead.source", label="Source", description="Lead-source enum value."),
    Variable(path="lead.won_value", label="Won value", description="Deal value on win."),
)

_RUNTIME_STANDARD: tuple[Variable, ...] = (
    Variable(
        path="run.channel",
        label="Channel",
        description="Channel the inbound arrived on.",
        sample="whatsapp",
    ),
    Variable(
        path="run.last_inbound_text",
        label="Last inbound text",
        description="The most recent customer message text.",
        sample="Hi, I want to see prices",
    ),
    Variable(
        path="run.contact_id",
        label="Contact ID",
        description="UUID of the linked contact.",
    ),
    Variable(
        path="run.conversation_id",
        label="Conversation ID",
        description="UUID of the current conversation thread.",
    ),
)


async def list_variables(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[VariableGroup]:
    """Build the full picker payload for one org.

    Groups are returned in the display order the frontend renders them
    (Contact → Contact custom → Lead → Lead custom → Runtime). Empty
    custom-field groups are omitted so the picker doesn't show an empty
    accordion header.
    """
    groups: list[VariableGroup] = [
        VariableGroup(key="contact", label="Contact", variables=list(_CONTACT_STANDARD)),
    ]

    contact_custom = await _custom_field_variables(
        session, org_id=org_id, entity_type="contact", scope_prefix="contact.custom"
    )
    if contact_custom:
        groups.append(
            VariableGroup(
                key="contact_custom",
                label="Contact — Custom fields",
                variables=contact_custom,
            )
        )

    groups.append(VariableGroup(key="lead", label="Lead", variables=list(_LEAD_STANDARD)))

    lead_custom = await _custom_field_variables(
        session, org_id=org_id, entity_type="lead", scope_prefix="lead.custom"
    )
    if lead_custom:
        groups.append(
            VariableGroup(
                key="lead_custom",
                label="Lead — Custom fields",
                variables=lead_custom,
            )
        )

    groups.append(
        VariableGroup(key="runtime", label="Runtime", variables=list(_RUNTIME_STANDARD))
    )

    return groups


async def _custom_field_variables(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    scope_prefix: str,
) -> list[Variable]:
    """Materialise this org's custom fields for one entity into
    :class:`Variable` rows. Skips fields whose ``field_key`` doesn't
    round-trip through the save-target validator's key regex — same
    guard as :mod:`save_target_registry` uses on the write side."""
    rows = await _dal.list_visible_custom_fields_for_org(
        session, org_id=org_id, entity_type=entity_type
    )
    out: list[Variable] = []
    for cf in rows:
        if not _CUSTOM_KEY_RE.match(cf.field_key):
            continue
        out.append(
            Variable(
                path=f"{scope_prefix}.{cf.field_key}",
                label=cf.field_label,
                description=f"Custom {entity_type} field ({cf.field_type.value if hasattr(cf.field_type, 'value') else cf.field_type}).",
            )
        )
    return out


__all__ = ["Variable", "VariableGroup", "list_variables"]
