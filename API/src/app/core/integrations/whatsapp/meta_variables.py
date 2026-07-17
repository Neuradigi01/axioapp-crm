"""Named ↔ positional variable conversion for Meta WhatsApp templates.

Our CRM lets operators author templates with **named, dot-scoped
variables** — ``{{contact.first_name}}``, ``{{org.name}}`` — because
that's the natural way marketing people think and because the same
tag renders across Email / SMS / WA via the shared variable registry.

Meta's WhatsApp Business API, however, only accepts **positional**
placeholders in the template body:

    Hi {{1}} 🪔, welcome to {{2}}!

Named tags with dots (``{{contact.first_name}}``) are rejected at
``/message_templates`` submit with the generic ``INVALID_FORMAT``.

This module bridges the two worlds:

  * :func:`convert_to_positional` — parse the CRM body, deduplicate
    variables in order of first appearance, rewrite the body with
    ``{{1}}`` / ``{{2}}`` / ... and return the ordered list of
    original CRM names so the caller can reverse the mapping later.

  * :func:`sample_examples` — resolve each named variable to a
    friendly sample string that Meta's reviewer sees during approval.
    Backed by a small in-module context of realistic Indian names /
    orgs so the sample looks legitimate to a Meta approver.

  * :func:`convert_all_components` — wraps ``convert_to_positional``
    over every text-bearing component (HEADER text, BODY, BUTTONS URL
    dynamic suffix). Returns the transformed components list + the
    per-component list of param names so the send-time renderer can
    populate Meta's parameter arrays.

No state persisted here — every call is deterministic against the
input text, so we can re-run at submit-time and re-run at send-time
and always agree on positional indexes.
"""

from __future__ import annotations

import re
from typing import Any

# Same regex the preview pane + variable-picker use. Dot-scoped names
# (e.g. ``contact.first_name``) and plain single-word names
# (``first_name``) both match. Positional placeholders like ``{{1}}``
# match too but are excluded from conversion — see the digit-only
# short-circuit inside ``convert_to_positional``.
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")

# Small sample context — Meta shows these to human reviewers in the
# template's preview during approval. Names / orgs picked to look
# plausible for our target market (India SMB CRMs). If the operator
# uses a variable we don't have a sample for, we fall back to a
# placeholder derived from the tag itself so Meta still gets a value.
_SAMPLE_CONTEXT: dict[str, str] = {
    "contact.first_name": "Ajay",
    "contact.last_name": "Gogane",
    "contact.full_name": "Ajay Gogane",
    "contact.email": "ajay@example.com",
    "contact.phone": "+919876543210",
    "first_name": "Ajay",
    "last_name": "Gogane",
    "full_name": "Ajay Gogane",
    "org.name": "Neuradigi",
    "org.support_email": "support@neuradigi.com",
    "org.support_phone": "+918000000000",
    "org.address": "42 MG Road, Bengaluru",
    "org.website": "https://neuradigi.com",
    "user.full_name": "Ajay Gogane",
    "user.email": "ajay@neuradigi.com",
    "user.role": "Owner",
    "appointment.scheduled_at": "Mon, 15 Jul · 11:00 AM",
    "appointment.location": "Neuradigi Office, Bengaluru",
    "appointment.notes": "Please bring the RFP document.",
    "invoice.id": "INV-2026-0421",
    "invoice.total_amount": "₹45,000",
    "invoice.currency": "INR",
    "invoice.due_date": "30 Jul 2026",
    "invoice.pdf_url": "https://neuradigi.com/invoices/0421.pdf",
    "lead.source": "Website",
    "lead.status": "Qualified",
    "lead.score": "78",
    "lead.estimated_value": "₹45,000",
    "lead.owner_name": "Ajay Gogane",
    "quote.id": "Q-2026-1042",
    "quote.total_amount": "₹45,000",
    "quote.currency": "INR",
    "quote.expires_at": "12 Jul 2026",
    "quote.pdf_url": "https://neuradigi.com/quotes/1042.pdf",
}


def convert_to_positional(text: str) -> tuple[str, list[str]]:
    """Rewrite ``text`` with positional placeholders and return the
    ordered param name list.

    Rules:

    * ``{{1}}`` / ``{{2}}`` / ... (already positional) pass through
      unchanged and are NOT added to the param name list — the
      operator opted out of the CRM's named model on purpose.
    * Named variables are numbered in order of first appearance. A
      variable used twice keeps the same positional index (Meta
      allows this — repeat parameters reference the same slot).
    * Whitespace inside the braces is trimmed so ``{{ contact.first_name }}``
      matches ``{{contact.first_name}}``.

    Examples::

        >>> convert_to_positional("Hi {{contact.first_name}}, ...")
        ('Hi {{1}}, ...', ['contact.first_name'])

        >>> convert_to_positional("{{a.b}} {{c.d}} {{a.b}}")
        ('{{1}} {{2}} {{1}}', ['a.b', 'c.d'])

        >>> convert_to_positional("Static text — no vars")
        ('Static text — no vars', [])
    """
    if not text:
        return text, []

    names_in_order: list[str] = []
    seen: dict[str, int] = {}

    def _sub(match: re.Match[str]) -> str:
        tag = match.group(1)
        # Already positional — leave it alone. Doesn't consume a slot
        # in our name list because we don't manage it.
        if tag.isdigit():
            return match.group(0)
        if tag not in seen:
            seen[tag] = len(names_in_order) + 1
            names_in_order.append(tag)
        return "{{" + str(seen[tag]) + "}}"

    return _VAR_RE.sub(_sub, text), names_in_order


def sample_examples(param_names: list[str]) -> list[str]:
    """Given a list of CRM variable names (in positional order),
    return the sample values Meta's reviewer sees.

    Falls back to a title-cased version of the tag's tail segment
    when the sample context has no entry — e.g. an unknown
    ``{{custom.deal_size}}`` becomes ``"Deal Size"``. Ensures Meta
    never sees an empty example (which would trigger its own
    ``INVALID_FORMAT``).
    """
    out: list[str] = []
    for name in param_names:
        sample = _SAMPLE_CONTEXT.get(name)
        if sample is None:
            tail = name.rsplit(".", 1)[-1]
            sample = tail.replace("_", " ").title() or "Sample"
        out.append(sample)
    return out


def convert_all_components(
    components: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Walk every text-bearing component in ``components`` and rewrite
    it to positional. Returns:

    * The new components list — safe to send to Meta as-is. HEADER
      TEXT + BODY get their ``text`` rewritten; each also gets an
      ``example`` sibling attached (Meta requires examples for any
      component that carries positional placeholders).
    * A mapping ``{"body": [...], "header": [...]}`` of param names
      per component so the send-time renderer can substitute real
      values.

    Idempotent on already-positional inputs — the digit-only
    short-circuit inside ``convert_to_positional`` skips them and
    returns an empty name list, so re-conversion is a no-op.
    """
    out: list[dict[str, Any]] = []
    mapping: dict[str, list[str]] = {}

    for comp in components:
        c = dict(comp)  # shallow copy — never mutate the caller's dict
        ctype = str(c.get("type", "")).upper()

        if ctype == "BODY" and isinstance(c.get("text"), str):
            new_text, names = convert_to_positional(c["text"])
            c["text"] = new_text
            if names:
                c["example"] = {"body_text": [sample_examples(names)]}
                mapping["body"] = names

        elif ctype == "HEADER" and c.get("format") == "TEXT":
            if isinstance(c.get("text"), str):
                new_text, names = convert_to_positional(c["text"])
                c["text"] = new_text
                if names:
                    c["example"] = {"header_text": sample_examples(names)}
                    mapping["header"] = names

        # FOOTER + BUTTONS have their own rules — footer text is
        # static (Meta forbids variables), buttons take fixed URL/
        # phone_number literals (dynamic-URL buttons are a separate
        # feature we haven't wired). Leave them untouched.

        out.append(c)

    return out, mapping


__all__ = [
    "convert_all_components",
    "convert_to_positional",
    "sample_examples",
]
