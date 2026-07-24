"""Field-spec metadata for the customer-friendly condition builder.

Each ``CatalogEntry`` in :mod:`core.automation.event_catalog` declares
a ``condition_fields`` tuple of :class:`FieldSpec` — the set of fields
the "Only if" builder's dropdown surfaces for that event. The
frontend reads them via ``GET /api/v1/automations/event-types`` and
renders a data-driven UI (grouped field picker, type-filtered
operator dropdown, type-aware value input) with zero per-event code
paths.

Design contract (step-1 of ``tasks/automation-conditions/``):

* Static per-deploy — same for every tenant. No ``org_id``, no DB row.
  A ``tbl_condition_field_catalog`` would just create a drift surface
  because the emit call and the field spec ship together as one code
  change; splitting them across code + DB helps nobody.
* Enum *values* are NOT stored on the spec — they come from a live
  per-org resolver (step-2) keyed by ``enum_resolver``. Pipeline
  stages, lead sources, user roles, tags all read the caller org's
  actual rows so a customer's dropdown never shows a hardcoded label
  that doesn't match their configuration.
* Startup-time drift guard: the ``event_catalog._register`` guard
  walks each spec's dot-path against the entry's ``sample_payload``
  and raises ``ValueError`` if the path can't resolve. Catches
  ``lead.stage`` vs ``lead.pipeline_stage`` typos the moment code
  lands, before a customer ever picks the wrong field and the
  evaluator silently no-matches every event.

Adding a new event's fields:

1. Reference the group with one of the ``GROUP_*`` constants — keeps
   the frontend section ordering consistent.
2. If the field's type is ``enum``, the ``enum_resolver`` key MUST
   match a resolver registered in step-2's
   :mod:`core.automation.enum_resolvers`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FieldType(StrEnum):
    """Wire-friendly type tags the frontend uses to pick an operator
    set and a value-input widget."""

    text = "text"
    number = "number"
    currency = "currency"
    date = "date"
    datetime = "datetime"
    boolean = "boolean"
    enum = "enum"


# Suggested group names. Free-string on the spec so a future event
# can invent a group without touching this module, but every existing
# event pulls from this list so the frontend renders a stable set of
# section headers ("── Contact ──", "── Lead ──", …). Order in this
# module matches the frontend's preferred display order (contact-first
# because that's what a customer usually thinks about).
GROUP_CONTACT = "Contact"
GROUP_LEAD = "Lead"
GROUP_TRANSITION = "Transition"
GROUP_APPOINTMENT = "Appointment"
GROUP_QUOTE = "Quote"
GROUP_INVOICE = "Invoice"
GROUP_USER = "User"
GROUP_ORG = "Org"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One customer-facing filter field on an event.

    :attr:`path`
        Dot-path into the event payload — e.g. ``"lead.pipeline_stage"``
        or ``"to_user_id"``. Must resolve against the enclosing
        entry's ``sample_payload`` at import time (drift guard in
        ``event_catalog._register``).

    :attr:`label`
        Human string the field dropdown shows — e.g. ``"Stage"``,
        ``"Assigned to"``. Never the raw path.

    :attr:`type`
        Drives the operator dropdown filter + the value-input widget.
        The evaluator itself is type-agnostic; this is UI metadata.

    :attr:`group`
        Section header the field is grouped under in the frontend
        dropdown. Prefer the ``GROUP_*`` constants above.

    :attr:`enum_resolver`
        Registry key for step-2's live enum resolver. REQUIRED when
        ``type == FieldType.enum``; FORBIDDEN otherwise (enforced by
        :meth:`__post_init__`).

    :attr:`help_text`
        Optional one-line hint. Renders under the field in the
        dropdown — use for non-obvious fields ("From stage — the
        stage the lead was in BEFORE this change fired").
    """

    path: str
    label: str
    type: FieldType
    group: str
    enum_resolver: str | None = None
    help_text: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("FieldSpec.path must be non-empty")
        if not self.label.strip():
            raise ValueError(f"FieldSpec.label must be non-empty (path={self.path!r})")
        if not self.group.strip():
            raise ValueError(f"FieldSpec.group must be non-empty (path={self.path!r})")
        if self.type is FieldType.enum and not self.enum_resolver:
            raise ValueError(
                f"FieldSpec(path={self.path!r}, type=enum) requires enum_resolver; "
                "declare a resolver key that step-2's registry provides."
            )
        if self.type is not FieldType.enum and self.enum_resolver is not None:
            raise ValueError(
                f"FieldSpec(path={self.path!r}, type={self.type.value}) must NOT set "
                f"enum_resolver — only enum fields dispatch to the resolver registry."
            )


_MISSING = object()


def walk_path(payload: object, path: str) -> object:
    """Walk a dot-path through nested dicts and return the leaf value.

    Returns the sentinel :data:`_MISSING` when any intermediate key is
    absent or a non-dict is encountered before the leaf. Caller
    treats a ``_MISSING`` return as "path does not exist" — the
    drift guard raises, the runtime evaluator no-matches. Never
    raises for a missing key.

    Lists are treated as opaque leaves — this catalog never declares
    condition fields inside arrays (evaluator has no ``[0]`` syntax
    either), so a list on the way to the leaf means the path is bad.

    A ``None`` value at the leaf is still a valid resolution — the
    payload legitimately carries ``None`` for e.g. ``from_user_id``
    on a first-time lead assignment, and the customer should be able
    to filter for it via the ``is empty`` operator.
    """
    node: object = payload
    for segment in path.split("."):
        if not isinstance(node, dict):
            return _MISSING
        if segment not in node:
            return _MISSING
        node = node[segment]
    return node


def path_resolves(payload: object, path: str) -> bool:
    """True when :func:`walk_path` finds the leaf (even if leaf is
    ``None``). Used by the drift guard + the coverage pin-test."""
    return walk_path(payload, path) is not _MISSING


__all__ = [
    "GROUP_APPOINTMENT",
    "GROUP_CONTACT",
    "GROUP_INVOICE",
    "GROUP_LEAD",
    "GROUP_ORG",
    "GROUP_QUOTE",
    "GROUP_TRANSITION",
    "GROUP_USER",
    "FieldSpec",
    "FieldType",
    "path_resolves",
    "walk_path",
]
