"""Live enum value resolvers for the customer-friendly condition
builder (``tasks/automation-conditions/`` Step 2).

Each ``FieldSpec`` on an event whose ``type`` is ``enum`` declares
an ``enum_resolver`` key (e.g. ``"pipeline_stages"``,
``"lead_sources"``). When the customer picks that field in the
condition builder, the frontend fires
``POST /automations/event-types/{event}/field-values`` and the
service dispatches through this registry: look up the resolver by
key, call it with the caller org's ``org_id``, return the org's
actual options.

Design invariants:

* Same registry pattern as :mod:`core.conversations.registry` and the
  module-registry — a per-process module-level dict, populated at
  import time. Multi-worker deploys stay consistent because every
  worker re-runs the module-level ``register_resolver`` calls.
* Resolvers are ``async def (session, org_id) -> list[EnumOption]``.
  Static resolvers ignore ``session``; DB-backed resolvers delegate
  to the owning module's ``data_access.py`` (never inline SQL — the
  layered-architecture pin-test enforces that).
* ``register_resolver`` is idempotent for same-callable re-registers
  (harmless module reloads / test-order shuffles) but raises on
  same-key + different-callable — that means two modules picked the
  same key by accident, which would silently overwrite one of them.
* ``get_resolver`` returns ``None`` for unknown keys so the router
  can 404 cleanly rather than the service raising a hard error.

Adding a new resolver:

1. Write ``async def resolve_<name>(session, org_id) -> list[EnumOption]``.
2. Add a ``register_resolver("<name>", resolve_<name>)`` call at the
   bottom of this file (or, for pack-owned resolvers, at the bottom
   of the pack's ``event_catalog.py`` — see step-7).
3. Reference the key from one or more ``FieldSpec`` entries in
   :mod:`core.automation.event_catalog`.

Pack-owned resolver keys (step-7) plug into the same registry;
convention is to prefix pack keys with the pack id (e.g.
``fp_warehouses``) so core + pack keys never collide.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.billing.models import InvoiceStatus, PaymentMethod
from src.app.core.conversations.models import ConversationChannel
from src.app.core.leads.models import LeadSource, LeadStatus

# Static default appointment purposes. The appointments module keeps
# ``purpose`` as a free-text column (no enum) so packs and customers
# can add their own — this default vocabulary covers the common
# purpose values customers filter on. Anything not in this list can
# still be authored via the condition builder's Advanced mode.
_DEFAULT_APPOINTMENT_PURPOSES: tuple[tuple[str, str], ...] = (
    ("consultation", "Consultation"),
    ("demo", "Demo"),
    ("follow_up", "Follow up"),
    ("showroom_visit", "Showroom visit"),
    ("site_visit", "Site visit"),
    ("delivery", "Delivery"),
    ("other", "Other"),
)


@dataclass(frozen=True, slots=True)
class EnumOption:
    """One row in an enum value dropdown.

    :attr:`value` — the raw string stored in the condition AST (must
    match what the runtime evaluator compares against). :attr:`label`
    — human display text for the dropdown.
    """

    value: str
    label: str


# Resolver signature: async callable returning the caller org's
# options. Static resolvers ignore ``session``; DB-backed resolvers
# read from it. ``org_id`` is passed even to static resolvers so the
# service layer can call every resolver uniformly.
EnumResolver = Callable[[AsyncSession, uuid.UUID], Coroutine[Any, Any, list[EnumOption]]]


_REGISTRY: dict[str, EnumResolver] = {}


def register_resolver(key: str, fn: EnumResolver) -> None:
    """Register a resolver under ``key``.

    Idempotent for the exact same callable (harmless during test
    reloads); raises ``RuntimeError`` if a different callable is
    registered under an already-taken key — that means two modules
    accidentally picked the same key, which would silently overwrite
    one behaviour with the other.
    """
    if not key:
        raise ValueError("resolver key must be non-empty")
    existing = _REGISTRY.get(key)
    if existing is not None and existing is not fn:
        raise RuntimeError(
            f"enum_resolver key {key!r} is already registered to a different "
            f"callable ({existing!r}); pick a distinct key or reuse the same "
            f"resolver function."
        )
    _REGISTRY[key] = fn


def get_resolver(key: str) -> EnumResolver | None:
    """Return the resolver registered under ``key``, or ``None`` if
    the key is unknown. The router maps ``None`` to a 404."""
    return _REGISTRY.get(key)


def list_registered_keys() -> list[str]:
    """Sorted list of every currently-registered resolver key.

    Used by the step-1 coverage pin-test to validate every
    ``FieldSpec.enum_resolver`` references a real key at test time.
    """
    return sorted(_REGISTRY.keys())


def _unregister(key: str) -> None:
    """Test helper — drop a previously registered resolver."""
    _REGISTRY.pop(key, None)


# --- static resolvers -----------------------------------------------


def _from_enum(cls: type, *, labels: dict[str, str] | None = None) -> list[EnumOption]:
    """Turn a ``(str, Enum)`` class into a list of options.

    Labels default to a Title-Cased version of the enum value; pass
    ``labels`` to override specific members (e.g. ``upi`` → ``UPI``
    rather than ``Upi``).
    """
    out: list[EnumOption] = []
    label_overrides = labels or {}
    for member in cls:
        value = member.value
        override = label_overrides.get(value)
        label = override if override is not None else value.replace("_", " ").title()
        out.append(EnumOption(value=value, label=label))
    return out


async def resolve_lead_sources(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Static — the platform-wide list of ingestion channels.
    Pack-owned sources register in step-7 under different keys."""
    return _from_enum(
        LeadSource,
        labels={
            "google_ads": "Google Ads",
            "meta_ads": "Meta Ads",
            "whatsapp_flow": "WhatsApp Flow",
        },
    )


async def resolve_lead_statuses(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Static — active / won / lost."""
    return _from_enum(LeadStatus)


async def resolve_appointment_purposes(
    _session: AsyncSession, _org_id: uuid.UUID
) -> list[EnumOption]:
    """Static — the built-in purpose vocabulary. Free-string on the
    appointments table so packs / customers can add their own; the
    "Advanced" mode in the condition builder handles the long tail."""
    return [EnumOption(value=v, label=lbl) for v, lbl in _DEFAULT_APPOINTMENT_PURPOSES]


async def resolve_invoice_statuses(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Static — draft / issued / paid / void."""
    return _from_enum(InvoiceStatus)


async def resolve_payment_methods(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Static — cash / card / upi / emi / cheque / bank."""
    return _from_enum(
        PaymentMethod,
        labels={"upi": "UPI", "emi": "EMI"},
    )


async def resolve_direction_updown(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Static — the two directions the ``lead.score_threshold`` event
    can fire in."""
    return [
        EnumOption(value="up", label="Crossed up"),
        EnumOption(value="down", label="Crossed down"),
    ]


async def resolve_channels(_session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Static — the platform's message channels. Includes every
    transport the templates library / conversations module recognise."""
    return _from_enum(ConversationChannel)


# --- DB-backed resolvers --------------------------------------------


async def resolve_pipeline_stages(session: AsyncSession, _org_id: uuid.UUID) -> list[EnumOption]:
    """Live — the caller org's Leads pipeline stages, in display
    order. Empty when the org hasn't been seeded / has deleted every
    stage — the frontend renders the "no stages configured" hint."""
    # Local import: keeps enum_resolvers importable even if the
    # pipelines module hasn't finished loading (protects against
    # accidental circular imports during app startup).
    from src.app.core.pipelines import data_access as pipelines_dal

    pipeline = await pipelines_dal.get_pipeline_by_key_with_stages(session, "leads")
    if pipeline is None:
        return []
    return [
        EnumOption(value=stage.key, label=stage.name)
        for stage in sorted(pipeline.stages, key=lambda s: s.display_order)
    ]


async def resolve_users(session: AsyncSession, org_id: uuid.UUID) -> list[EnumOption]:
    """Live — the caller org's active team members (id → full name).

    The value is the user's UUID (matches how events emit
    ``assigned_to_id`` / ``to_user_id`` / ``from_user_id``), the
    label is the full name. Ordered by email for stable UI.
    """
    from src.app.core.users import data_access as users_dal

    # 500 upper bound is generous — real orgs top out around 50-100
    # active users. If a customer ever crosses 500 they'll still see
    # a working (if long) dropdown; step-3 can add server-side search
    # if the need arises.
    users = await users_dal.list_users_in_org(session, org_id=org_id, limit=500, offset=0)
    return [EnumOption(value=str(u.id), label=u.full_name) for u in users if u.full_name]


# --- registration ---------------------------------------------------
#
# Registered at module import so every ``FieldSpec.enum_resolver``
# key referenced by :mod:`core.automation.event_catalog` finds its
# resolver by the time the app boots. ``core.automation.__init__``
# imports this module for the side-effect.

register_resolver("lead_sources", resolve_lead_sources)
register_resolver("lead_statuses", resolve_lead_statuses)
register_resolver("appointment_purposes", resolve_appointment_purposes)
register_resolver("invoice_statuses", resolve_invoice_statuses)
register_resolver("payment_methods", resolve_payment_methods)
register_resolver("direction_updown", resolve_direction_updown)
register_resolver("channels", resolve_channels)
register_resolver("pipeline_stages", resolve_pipeline_stages)
register_resolver("users", resolve_users)


__all__ = [
    "EnumOption",
    "EnumResolver",
    "_unregister",
    "get_resolver",
    "list_registered_keys",
    "register_resolver",
    "resolve_appointment_purposes",
    "resolve_channels",
    "resolve_direction_updown",
    "resolve_invoice_statuses",
    "resolve_lead_sources",
    "resolve_lead_statuses",
    "resolve_payment_methods",
    "resolve_pipeline_stages",
    "resolve_users",
]
