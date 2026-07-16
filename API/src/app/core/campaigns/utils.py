"""Pure helpers for the campaigns engine.

Split out from :mod:`service.py` so the leaf logic can be imported by
Celery tasks + tests without pulling the whole service module (which
touches the DB layer). Everything here is stateless.

Two related concerns:

  * WhatsApp positional ``{{n}}`` binding resolution — reused by both
    the WA template dispatch path and the A/B decider. See
    :func:`resolve_positional_variables`.
  * Named ``{{first_name}}`` merge-tag substitution — used by the
    Email dispatch path (Campaigns v1 Step 05) and the legacy WA
    free-text campaign body renderer.

The pre-Step-05 WA-only helpers were named ``_render_template`` /
``_get_contact_field`` / ``_resolve_template_variables`` and lived in
service.py. They still live there — this module only adds the
Email-friendly helpers so the WA code path stays byte-identical while
Email gets a first-class rendering surface.
"""

from __future__ import annotations

import re
from typing import Any

# --- Named merge-tag substitution (Email) -------------------------------


# Fallback for empty contact fields — matches the legacy WA behaviour
# in service.py::_TEMPLATE_FIELD_FALLBACK so a template rendered by
# either code path lands the same "Customer" instead of an empty string
# in the outbound message.
MERGE_TAG_FALLBACK = "Customer"


_NAMED_MERGE_TAG_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")


def _split_full_name(full_name: str | None) -> tuple[str, str]:
    """Best-effort split of a single ``full_name`` string into
    ``(first, last)``. Handles the common ``"First Last"`` shape;
    single-token names return ``("First", "")``. Not culturally
    universal — real segmentation would need per-contact fields — but
    good enough for merge-tag rendering."""
    if not full_name:
        return ("", "")
    trimmed = full_name.strip()
    if not trimmed:
        return ("", "")
    parts = trimmed.split(None, 1)
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


def _lookup_contact_attr(contact: Any, name: str) -> str:
    """Resolve a merge-tag name against a Contact-like object.

    Supported tag names (case-sensitive):

      * ``first_name`` / ``last_name`` / ``full_name``
      * ``email`` / ``phone``
      * ``custom_data.<key>`` — reads from the JSONB column
      * ``contact.<field>`` — namespaced form of any of the above

    Unknown names return ``""`` (empty) — the caller decides whether to
    substitute the fallback or leave the placeholder intact.
    """
    if name.startswith("contact."):
        name = name.split(".", 1)[1]

    if name == "full_name":
        return contact.full_name or ""
    if name == "first_name":
        first, _ = _split_full_name(contact.full_name)
        return first
    if name == "last_name":
        _, last = _split_full_name(contact.full_name)
        return last
    if name == "email":
        return contact.email or ""
    if name == "phone":
        return contact.phone or ""
    if name.startswith("custom_data."):
        key = name.split(".", 1)[1]
        custom = getattr(contact, "custom_data", None) or {}
        value = custom.get(key)
        return str(value) if value not in (None, "") else ""
    return ""


def substitute_merge_tags(source: str | None, contact: Any) -> str:
    """Substitute every ``{{name}}`` occurrence in ``source`` with the
    matching contact attribute. Empty resolutions fall back to
    :data:`MERGE_TAG_FALLBACK` to avoid emailing a "Hi ," greeting.
    Unknown names are left intact so a typo doesn't blow up the send —
    the operator sees the literal ``{{unknown}}`` in the delivered
    message which is a strong "fix your template" signal.
    """
    if not source:
        return ""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = _lookup_contact_attr(contact, name)
        if value:
            return value
        # Reserve the fallback for well-known missing fields — an
        # unknown name looks like a typo, so we leave it visible.
        known = {
            "full_name",
            "first_name",
            "last_name",
            "email",
            "phone",
        }
        base = name.split(".", 1)[0]
        if name in known or base in known or name.startswith("contact.") or name.startswith(
            "custom_data."
        ):
            return MERGE_TAG_FALLBACK
        return match.group(0)

    return _NAMED_MERGE_TAG_RE.sub(_sub, source)


def render_subject(subject: str | None, contact: Any) -> str:
    """Convenience — subject lines only support the same named tags as
    bodies. Kept as a distinct entry point so callers can grep for
    "render_subject" when tracing an odd subject line."""
    return substitute_merge_tags(subject, contact)


def render_body(body: str | None, contact: Any) -> str:
    """Convenience — html + text bodies substitute the same set of
    named tags. Emitting an alias means callers don't have to guess
    which helper to reach for."""
    return substitute_merge_tags(body, contact)


__all__ = [
    "MERGE_TAG_FALLBACK",
    "render_body",
    "render_subject",
    "substitute_merge_tags",
]
