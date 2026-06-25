"""Shared variable substitution engine + per-channel registry.

Re-houses the original :mod:`core.email.variables` here so every
channel (WhatsApp, Email, SMS, FB / IG Direct, Push) can share one
parser, one renderer, and one allow-list. ``core/email/variables.py``
now re-exports from this module — existing callers don't change.

The engine ships five public operations:

  - :func:`extract_variable_paths` (alias :func:`extract_variables`)
    scans the body for every ``{{ a.b.c }}`` token and returns a
    sorted, deduped list of dot-paths. The service uses this to
    populate ``tbl_message_templates.variables`` on create / update.
  - :func:`reject_jinja_statements` raises
    :class:`TemplateSyntaxError` if any ``{% ... %}`` or
    ``{# ... #}`` constructs are present. Defends against operators
    pasting Jinja-style conditionals we don't render correctly.
  - :func:`render` substitutes every dot-path against ``context``.
    Strict by default — raises :class:`MissingVariable` listing every
    path that couldn't be resolved. Preserves the contract every
    existing email caller relies on.
  - :func:`resolve` is the lenient counterpart for downstream callers
    (Step-4 automation triggers, future Workflows dispatcher) where a
    partially-populated event payload is normal. Missing paths
    substitute to an empty string instead of raising. Never leaks the
    raw ``{{...}}`` token to the customer.
  - :data:`ALLOWED_VARIABLES_BY_CHANNEL` is the editor's source of
    truth for what ``{{tags}}`` the variable-picker UI shows per
    channel. The variables namespace is shared (one ``contact.*``
    means the same thing everywhere); the registry only controls
    which namespaces a given channel surfaces.

The renderer pointedly avoids Jinja2:

  * Jinja2 isn't in this repo's pinned dependencies and pulling it
    in for one feature adds meaningful attack surface (sandbox
    escapes are a recurring Jinja2 CVE class: CVE-2024-22195,
    CVE-2024-34064).
  * The spec rejects ``{% ... %}`` constructs anyway; a hand-rolled
    50-line engine is more auditable.
"""
from __future__ import annotations

import enum
import html
import re
from dataclasses import dataclass
from typing import Any

from src.app.core.conversations.models import ConversationChannel


# Variable token: ``{{ a.b.c }}``. Whitespace tolerated inside; path
# is lowercase + underscores + dots, strict enough that a stray ``{``
# doesn't get eaten.
_VAR_TOKEN_RE = re.compile(
    r"\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)\s*\}\}"
)

# Forbidden constructs: Jinja statements + comments. Either triggers a
# save-time rejection.
_JINJA_STATEMENT_RE = re.compile(r"\{%.+?%\}", re.DOTALL)
_JINJA_COMMENT_RE = re.compile(r"\{#.+?#\}", re.DOTALL)


class TemplateSyntaxError(ValueError):
    """Raised when the template uses an unsupported construct
    (``{% ... %}`` / ``{# ... #}``) or an unrecognised variable shape."""


class MissingVariable(ValueError):
    """Raised by :func:`render` when one or more variable paths can't
    be resolved against the supplied context. ``paths`` carries every
    missing dot-path so the router can list them in a 400."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__(f"Missing variables: {', '.join(paths)}")
        self.paths: list[str] = list(paths)


# --- Variable definition registry --------------------------------------


class VariableType(str, enum.Enum):
    """Hints the editor's input widget + the renderer's coercion path."""

    string = "string"
    int_ = "int"
    date = "date"
    currency = "currency"
    url = "url"
    bool_ = "bool"


@dataclass(frozen=True, slots=True)
class VariableDef:
    """One row in the per-channel variable picker.

    ``key`` is the dot-path the body references (``contact.first_name``).
    ``label`` is the human-readable name in the editor sidebar.
    ``type`` hints the editor + the renderer (string vs date vs URL).
    ``required`` flags variables the editor warns the operator about
    when the body doesn't reference them ("you didn't use ``{{order.id}}``
    — order receipts usually do").
    """

    key: str
    label: str
    type: VariableType = VariableType.string
    required: bool = False
    default: str | None = None


# --- Namespace catalogs -------------------------------------------------

# Every namespace is sharable — ``{{contact.first_name}}`` means the
# same thing whether the template renders into an email or a WhatsApp
# message. Channels just opt into which namespaces their editor
# surfaces. The dispatcher walks the same dict regardless.

_CONTACT_VARS: tuple[VariableDef, ...] = (
    VariableDef("contact.first_name", "Contact first name"),
    VariableDef("contact.last_name", "Contact last name"),
    VariableDef("contact.full_name", "Contact full name"),
    VariableDef("contact.email", "Contact email"),
    VariableDef("contact.phone", "Contact phone"),
)

_ORG_VARS: tuple[VariableDef, ...] = (
    VariableDef("org.name", "Organisation name"),
    VariableDef("org.support_email", "Support email"),
    VariableDef("org.support_phone", "Support phone"),
    VariableDef("org.address", "Organisation address"),
    VariableDef("org.website", "Organisation website"),
)

_SENDER_VARS: tuple[VariableDef, ...] = (
    VariableDef("sender.name", "Sender name"),
    VariableDef("sender.email", "Sender email"),
    VariableDef("sender.role", "Sender role"),
    VariableDef("sender.signature", "Sender signature"),
)

_LEAD_VARS: tuple[VariableDef, ...] = (
    VariableDef("lead.source", "Lead source"),
    VariableDef("lead.status", "Lead status"),
    VariableDef("lead.score", "Lead score", type=VariableType.int_),
    VariableDef("lead.estimated_value", "Lead estimated value", type=VariableType.currency),
    VariableDef("lead.owner_name", "Lead owner name"),
)

_USER_VARS: tuple[VariableDef, ...] = (
    # Used by `user.signed_up` / `user.invited` / `user.password_reset`
    # events from the future automation-engine track.
    VariableDef("user.full_name", "User full name"),
    VariableDef("user.email", "User email"),
    VariableDef("user.role", "User role"),
)

_APPOINTMENT_VARS: tuple[VariableDef, ...] = (
    VariableDef("appointment.scheduled_at", "Appointment date/time", type=VariableType.date),
    VariableDef("appointment.location", "Appointment location"),
    VariableDef("appointment.notes", "Appointment notes"),
)

_QUOTE_VARS: tuple[VariableDef, ...] = (
    VariableDef("quote.id", "Quote ID"),
    VariableDef("quote.total_amount", "Quote total", type=VariableType.currency),
    VariableDef("quote.currency", "Quote currency"),
    VariableDef("quote.expires_at", "Quote expiry", type=VariableType.date),
    VariableDef("quote.pdf_url", "Quote PDF link", type=VariableType.url),
)

_INVOICE_VARS: tuple[VariableDef, ...] = (
    VariableDef("invoice.id", "Invoice ID"),
    VariableDef("invoice.total_amount", "Invoice total", type=VariableType.currency),
    VariableDef("invoice.currency", "Invoice currency"),
    VariableDef("invoice.due_date", "Due date", type=VariableType.date),
    VariableDef("invoice.pdf_url", "Invoice PDF link", type=VariableType.url),
)


# --- Per-channel allow-list --------------------------------------------

#: Which variable namespaces each channel's editor exposes in the
#: variable-picker UI. The renderer itself does NOT validate against
#: this list — a body using ``{{lead.status}}`` in an SMS template
#: still renders correctly so long as ``lead.status`` is in the
#: context. The list is a UX guard, not a security boundary.
ALLOWED_VARIABLES_BY_CHANNEL: dict[ConversationChannel, list[VariableDef]] = {
    ConversationChannel.email: [
        *_CONTACT_VARS,
        *_ORG_VARS,
        *_SENDER_VARS,
        *_LEAD_VARS,
        *_USER_VARS,
        *_APPOINTMENT_VARS,
        *_QUOTE_VARS,
        *_INVOICE_VARS,
    ],
    ConversationChannel.whatsapp: [
        *_CONTACT_VARS,
        *_ORG_VARS,
        *_LEAD_VARS,
        *_USER_VARS,
        *_APPOINTMENT_VARS,
        *_QUOTE_VARS,
        *_INVOICE_VARS,
    ],
    ConversationChannel.sms: [
        # SMS bodies are tight — surface only the high-signal short
        # values. Operators reaching for org.address are doing it wrong.
        VariableDef("contact.first_name", "Contact first name"),
        VariableDef("contact.full_name", "Contact full name"),
        VariableDef("org.name", "Organisation name"),
        VariableDef("appointment.scheduled_at", "Appointment date/time", type=VariableType.date),
        VariableDef("quote.id", "Quote ID"),
        VariableDef("invoice.id", "Invoice ID"),
    ],
    ConversationChannel.facebook: [
        *_CONTACT_VARS,
        *_ORG_VARS,
        *_LEAD_VARS,
    ],
    ConversationChannel.instagram: [
        *_CONTACT_VARS,
        *_ORG_VARS,
        *_LEAD_VARS,
    ],
    # Web push / in-app — title + body only, tiny variable set.
    ConversationChannel.web: [
        VariableDef("contact.first_name", "Contact first name"),
        VariableDef("org.name", "Organisation name"),
    ],
}


def variables_for_channel(channel: ConversationChannel) -> list[VariableDef]:
    """Return the variable picker list for ``channel`` (or empty list
    when the channel is unknown to the registry)."""
    return list(ALLOWED_VARIABLES_BY_CHANNEL.get(channel, []))


# --- Parser + renderer --------------------------------------------------


def extract_variable_paths(text: str) -> list[str]:
    """Return every dot-path referenced in ``text``, sorted + unique.

    ``{{ contact.first_name }} … {{ lead.value }} … {{ contact.first_name }}``
    → ``['contact.first_name', 'lead.value']``.
    """
    if not text:
        return []
    return sorted({match.group(1) for match in _VAR_TOKEN_RE.finditer(text)})


# Step-2 spec spelling — same semantics as :func:`extract_variable_paths`.
extract_variables = extract_variable_paths


def reject_jinja_statements(text: str) -> None:
    """Validate at save time that ``text`` carries no ``{% ... %}`` /
    ``{# ... #}`` constructs. Raises :class:`TemplateSyntaxError`."""
    if not text:
        return
    if _JINJA_STATEMENT_RE.search(text):
        raise TemplateSyntaxError(
            "Templates do not support `{% ... %}` constructs "
            "(if / for / block / include). Use plain "
            "`{{ contact.first_name }}` substitutions only."
        )
    if _JINJA_COMMENT_RE.search(text):
        raise TemplateSyntaxError(
            "Templates do not support `{# ... #}` comments. "
            "Strip them before saving."
        )


# Sentinel — distinguishable from None (a legitimate context value:
# ``contact.last_name`` is legitimately None for single-name contacts;
# we still substitute "").
_MISSING = object()


def _resolve_path(context: dict[str, Any], path: str) -> Any:
    """Walk a dot-path through nested dicts. Returns :data:`_MISSING`
    when any segment is absent so the caller can list missing paths."""
    current: Any = context
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def render(
    text: str,
    context: dict[str, Any],
    *,
    autoescape: bool = True,
) -> str:
    """Strict substitution. Raises :class:`MissingVariable` listing
    every unresolved path. Existing email callers rely on this — the
    raise lets the router 400 with a precise list of what's missing.

    ``autoescape=True`` HTML-escapes substituted values so user-typed
    content can't inject script tags into the rendered body. Pass
    ``autoescape=False`` for plain-text rendering where ``&amp;`` etc.
    would be undesirable.
    """
    if not text:
        return ""

    reject_jinja_statements(text)
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        path = match.group(1)
        value = _resolve_path(context, path)
        if value is _MISSING:
            missing.append(path)
            return ""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        rendered = str(value)
        return html.escape(rendered, quote=True) if autoescape else rendered

    output = _VAR_TOKEN_RE.sub(_sub, text)
    if missing:
        raise MissingVariable(sorted(set(missing)))
    return output


def resolve(
    text: str,
    context: dict[str, Any],
    *,
    autoescape: bool = True,
) -> str:
    """Lenient substitution. Missing paths become empty string instead
    of raising. Use this for automation / workflow dispatchers where
    a partial event payload is normal — never leaks raw ``{{tag}}`` to
    the customer either way.

    Strict callers (email send pipeline, "send now" UI button) keep
    using :func:`render` so they can show the operator a precise
    "missing X / Y" error before delivery.
    """
    if not text:
        return ""

    reject_jinja_statements(text)

    def _sub(match: re.Match[str]) -> str:
        path = match.group(1)
        value = _resolve_path(context, path)
        if value is _MISSING or value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        rendered = str(value)
        return html.escape(rendered, quote=True) if autoescape else rendered

    return _VAR_TOKEN_RE.sub(_sub, text)


__all__ = [
    "ALLOWED_VARIABLES_BY_CHANNEL",
    "MissingVariable",
    "TemplateSyntaxError",
    "VariableDef",
    "VariableType",
    "extract_variable_paths",
    "extract_variables",
    "reject_jinja_statements",
    "render",
    "resolve",
    "variables_for_channel",
]
