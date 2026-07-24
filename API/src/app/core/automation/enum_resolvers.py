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

from src.app.core.automation._pack_context import get_current_pack
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

# Wildcard registry — keys are prefixes ending in ``*`` (e.g.
# ``"custom_field_options:*"``). ``get_resolver`` falls through to
# these when the exact-match lookup misses. Enables step-6's
# custom-field-options resolver to serve any of the millions of
# possible ``custom_field_options:<entity>:<field_key>`` lookups
# without needing to register each one individually at boot.
_WILDCARD_REGISTRY: dict[str, EnumResolver] = {}

# Per-key pack ownership (tasks/automation-conditions/ Step 7). None
# for core resolvers (visible to every org); pack slug (e.g. "furniture")
# for pack-registered resolvers. Auto-populated from the pack-import
# ContextVar so pack files don't need to hardcode their own slug.
# Wildcard entries live under the same prefix keys as
# _WILDCARD_REGISTRY (the trailing ``*`` is stripped for storage).
_PACK_OWNERS: dict[str, str | None] = {}
_WILDCARD_PACK_OWNERS: dict[str, str | None] = {}


def register_resolver(key: str, fn: EnumResolver, *, wildcard: bool = False) -> None:
    """Register a resolver under ``key``.

    Idempotent for the exact same callable (harmless during test
    reloads); raises ``RuntimeError`` if a different callable is
    registered under an already-taken key — that means two modules
    accidentally picked the same key, which would silently overwrite
    one behaviour with the other.

    ``wildcard=True`` treats ``key`` as a prefix ending in ``*``.
    Lookups via :func:`get_resolver` first check exact matches,
    then fall through to wildcards whose prefix matches. Step-6's
    ``custom_field_options:*`` handler uses this to serve the
    per-org-per-field-key lookups without pre-registering every
    combination.

    Pack ownership (tasks/automation-conditions/ Step 7): if this
    call runs during a pack's ``event_catalog.py`` import (the
    module-registry walker sets the ContextVar for the duration),
    the registered key gets auto-tagged with the pack slug. Core
    resolvers stay ``None``. Query via :func:`pack_owner_for`.
    """
    if not key:
        raise ValueError("resolver key must be non-empty")
    owner = get_current_pack()
    if wildcard:
        if not key.endswith("*"):
            raise ValueError(f"wildcard resolver key {key!r} must end with '*'")
        prefix = key[:-1]
        if not prefix:
            raise ValueError("wildcard resolver key must have a non-empty prefix")
        existing = _WILDCARD_REGISTRY.get(prefix)
        if existing is not None and existing is not fn:
            raise RuntimeError(
                f"wildcard enum_resolver prefix {prefix!r} is already registered "
                f"to a different callable ({existing!r}); pick a distinct prefix "
                f"or reuse the same resolver function."
            )
        _WILDCARD_REGISTRY[prefix] = fn
        _WILDCARD_PACK_OWNERS[prefix] = owner
        return
    existing = _REGISTRY.get(key)
    if existing is not None and existing is not fn:
        raise RuntimeError(
            f"enum_resolver key {key!r} is already registered to a different "
            f"callable ({existing!r}); pick a distinct key or reuse the same "
            f"resolver function."
        )
    _REGISTRY[key] = fn
    _PACK_OWNERS[key] = owner


def get_resolver(key: str) -> EnumResolver | None:
    """Return the resolver registered under ``key``, or ``None`` if
    the key is unknown. Exact matches win; wildcard-prefix matches
    are a fallback (longest-prefix wins so more-specific handlers
    beat catch-alls if someone ever registers both). The router
    maps ``None`` to a 404."""
    exact = _REGISTRY.get(key)
    if exact is not None:
        return exact
    best_prefix = ""
    for prefix in _WILDCARD_REGISTRY:
        if key.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
    if best_prefix:
        return _WILDCARD_REGISTRY[best_prefix]
    return None


def list_registered_keys() -> list[str]:
    """Sorted list of every currently-registered resolver key.

    Includes exact keys plus wildcard prefixes appended with ``*``
    so callers can see the shape of what's dispatchable. Used by
    the step-1 coverage pin-test to validate every
    ``FieldSpec.enum_resolver`` references either a real key or is
    matched by a registered wildcard.
    """
    exacts = list(_REGISTRY.keys())
    wildcards = [f"{prefix}*" for prefix in _WILDCARD_REGISTRY]
    return sorted(exacts + wildcards)


def _unregister(key: str) -> None:
    """Test helper — drop a previously registered resolver (exact
    or wildcard). Wildcard keys must include the trailing ``*``."""
    if key.endswith("*"):
        prefix = key[:-1]
        _WILDCARD_REGISTRY.pop(prefix, None)
        _WILDCARD_PACK_OWNERS.pop(prefix, None)
        return
    _REGISTRY.pop(key, None)
    _PACK_OWNERS.pop(key, None)


def pack_owner_for(key: str) -> str | None:
    """Return the pack slug that registered ``key`` (or ``None`` for
    core-owned + unknown keys). Exact keys checked first, then the
    longest matching wildcard prefix. Callers use this to filter
    the ``/field-values`` endpoint by the caller org's ``template_id``
    (tasks/automation-conditions/ Step 7).
    """
    if key in _PACK_OWNERS:
        return _PACK_OWNERS[key]
    best_prefix = ""
    for prefix in _WILDCARD_REGISTRY:
        if key.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
    if best_prefix:
        return _WILDCARD_PACK_OWNERS.get(best_prefix)
    return None


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


# --- wildcard resolvers (tasks/automation-conditions/ Step 6) -------
#
# Wildcard resolvers dispatch to a generic handler that reads the
# per-org context out of the key itself. Used for custom-field
# option lookups where every (entity_type, field_key) combination
# would need its own registration — impractical when the set is
# per-org and unbounded.


async def resolve_custom_field_options(
    session: AsyncSession, org_id: uuid.UUID, resolver_key: str
) -> list[EnumOption]:
    """Wildcard-dispatch handler for keys shaped
    ``custom_field_options:<entity_type>:<field_key>``.

    Parses the key back into ``(entity_type, field_key)``, looks
    up the caller org's :class:`~core.custom_fields.models.CustomFieldDefinition`
    row for that pair, and turns its ``options.choices`` list into
    a value dropdown. Choices are stored as flat strings — value
    and label are the same string (matching what the customer
    typed under Settings → Custom Fields).

    Zero-rows cases:
      * Key not shaped correctly → returns ``[]`` (safer than
        raising; the endpoint should never dispatch an unparseable
        key thanks to the ``FieldSpec`` drift guard).
      * Definition not found for the org / entity / field → ``[]``
        (the frontend renders a "no options configured" hint).
      * ``options`` is null or missing the ``choices`` key → ``[]``
        (same treatment — the customer needs to add options under
        Settings first).

    Signature is broader than the base ``EnumResolver`` protocol so
    the wildcard-dispatch path can hand the raw key in. The
    protocol adapter in ``list_field_values`` (service) unpacks
    the key from the FieldSpec's ``enum_resolver`` before invoking.
    """
    from src.app.core.automation import custom_field_bridge
    from src.app.core.custom_fields.models import CustomFieldDefinition

    parsed = custom_field_bridge.parse_resolver_key(resolver_key)
    if parsed is None:
        return []
    entity_type, field_key = parsed

    from sqlalchemy import select as sa_select

    stmt = sa_select(CustomFieldDefinition).where(
        CustomFieldDefinition.org_id == org_id,
        CustomFieldDefinition.entity_type == entity_type,
        CustomFieldDefinition.field_key == field_key,
    )
    result = await session.execute(stmt)
    definition = result.scalar_one_or_none()
    if definition is None or not definition.options:
        return []
    choices = definition.options.get("choices") or []
    if not isinstance(choices, list):
        return []
    return [EnumOption(value=str(c), label=str(c)) for c in choices if isinstance(c, str) and c]


async def _custom_field_options_wildcard_dispatch(
    session: AsyncSession, org_id: uuid.UUID
) -> list[EnumOption]:
    """Placeholder — the wildcard registry stores this callable
    against the ``custom_field_options:*`` prefix so the router's
    ``get_resolver(key)`` call returns something callable. The
    actual per-request dispatch happens in
    :func:`core.automation.service.list_field_values` which passes
    the concrete resolver key through to
    :func:`resolve_custom_field_options`.
    """
    raise RuntimeError(
        "custom_field_options:* is a wildcard resolver — invoke "
        "resolve_custom_field_options(session, org_id, key) directly "
        "from the service layer."
    )


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

# Wildcard: matches every custom_field_options:<entity>:<field_key>
# key generated by step-6's custom-field bridge.
register_resolver(
    "custom_field_options:*",
    _custom_field_options_wildcard_dispatch,
    wildcard=True,
)


__all__ = [
    "EnumOption",
    "EnumResolver",
    "_unregister",
    "get_resolver",
    "list_registered_keys",
    "pack_owner_for",
    "register_resolver",
    "resolve_appointment_purposes",
    "resolve_channels",
    "resolve_custom_field_options",
    "resolve_direction_updown",
    "resolve_invoice_statuses",
    "resolve_lead_sources",
    "resolve_lead_statuses",
    "resolve_payment_methods",
    "resolve_pipeline_stages",
    "resolve_users",
]
