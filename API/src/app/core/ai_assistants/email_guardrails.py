"""Reply-worthiness filter for inbound email
(``tasks/ai-assistants-omnichannel`` Step 6).

Email inboxes are polluted with automated senders. Auto-replying to
every inbound would answer Amazon shipping notifications, Stripe
receipts, DMARC reports, Mailchimp campaigns, and every calendar
invite in the queue.

:func:`is_reply_worthy` is the single gate the AI email dispatch
calls before invoking the LLM. It enforces a deliberately conservative
allow-list of "real human email" characteristics based on RFC-defined
headers plus a small local-part deny-list. Pure function, no DB, no
network — safe to call inline on every inbound sync tick.

Determinism is intentional: an ML "worthy of reply" classifier is a
future consideration but not v1. Operators debugging "why did AI not
reply to X" should be able to read one function to answer.

Returns a two-tuple ``(should_reply, skip_reason)``:

  * ``(True, None)`` — email passes every gate.
  * ``(False, "<snake_case_reason>")`` — skipped; reason surfaces in
    the structured log line for post-hoc analytics.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


# --- Public shape --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InboundEmail:
    """The minimum email envelope the guardrail needs to decide.

    ``headers`` is a case-insensitive mapping (any dict-like where
    ``.get("List-Unsubscribe")`` finds ``"list-unsubscribe"`` too).
    Callers wrap the raw MIME headers into :class:`CaseInsensitiveDict`
    or similar; ``dict(str, str)`` also works if the caller pre-lowered
    the keys.
    """

    sender_email: str
    subject: str | None
    body_text: str
    headers: Mapping[str, str]


# --- Rule constants ------------------------------------------------------

# Local-parts we NEVER auto-reply to. Case-insensitive prefix + exact
# match. Kept short + high-signal — anything else (``support@`` /
# ``billing@`` / etc.) can plausibly be a real conversation.
_ROLE_LOCAL_PARTS: frozenset[str] = frozenset(
    {
        "no-reply",
        "noreply",
        "no_reply",
        "notifications",
        "notification",
        "postmaster",
        "bounces",
        "bounce",
        "mailer-daemon",
        "mailerdaemon",
        "do-not-reply",
        "donotreply",
        "hostmaster",
        "abuse",
        "root",
    }
)

# Bounce / auto-reply subject-line prefixes (case-insensitive).
_BOUNCE_SUBJECT_PREFIXES: tuple[str, ...] = (
    "delivery status notification",
    "undelivered mail",
    "returned mail",
    "mail delivery failed",
    "automatic reply",
    "out of office",
    "out-of-office",
    "auto:",
    "autoresponder:",
)

_MIN_BODY_CHARS_AFTER_QUOTE_STRIP: int = 1

# Case-insensitive matcher for a Gmail / Outlook / most-mail-clients
# quote header line, e.g. "On Mon, Aug 20 2025 at 11:42, Jane <j@x.com> wrote:".
_QUOTE_HEADER_RE = re.compile(
    r"^\s*(on\s+.+\bwrote:\s*$|from:\s+.+$|-----\s*original\s+message\s*-----)",
    re.IGNORECASE,
)


# --- Helpers -------------------------------------------------------------


def _local_part(email: str) -> str:
    """Extract the ``jane`` in ``jane@customer.com``. Falls back to the
    whole string when no ``@`` is present so the deny-list still fires
    on malformed rows rather than silently letting them through."""
    at = email.find("@")
    return (email[:at] if at >= 0 else email).strip().lower()


def _headers_lower(headers: Mapping[str, str]) -> dict[str, str]:
    """Materialise a lower-cased-keys copy so we can look up
    ``list-unsubscribe`` regardless of the wire capitalisation the
    provider chose. Values pass through untouched."""
    return {k.lower(): v for k, v in headers.items()}


def strip_quoted_history(body: str) -> str:
    """Return only the "new" text an operator would consider the
    message body — quoted history (``> `` prefixed lines, and
    everything below the ``On ... wrote:`` / ``From:`` / ``----
    Original Message ----`` divider) stripped.

    Not perfect against Outlook's HTML-formatted quotes, but sufficient
    for the "empty body under quoted history" guardrail check. Public
    so the future outbound-threading helper can reuse the exact same
    stripper when quoting inbound content."""
    lines: list[str] = []
    for line in body.splitlines():
        if _QUOTE_HEADER_RE.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# --- Main gate -----------------------------------------------------------


def is_reply_worthy(email: InboundEmail) -> tuple[bool, str | None]:
    """Return ``(True, None)`` iff every gate passes. On skip return
    ``(False, "<reason>")`` where the reason is a stable snake_case
    string suitable for a structured-log tag."""
    # 1. Sender local-part deny-list.
    local = _local_part(email.sender_email or "")
    if local in _ROLE_LOCAL_PARTS:
        return False, "sender_role_account"

    hdrs = _headers_lower(email.headers or {})

    # 2. RFC 3834 auto-response indicator. Only value ``no`` allows a
    #    reply; ``auto-replied`` / ``auto-generated`` / anything else
    #    is disqualifying.
    auto_submitted = (hdrs.get("auto-submitted") or "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return False, "auto_submitted_header"

    # 3. RFC 2369 list mailer indicator.
    if "list-unsubscribe" in hdrs:
        return False, "list_unsubscribe_header"

    # 4. Legacy bulk-precedence indicator.
    precedence = (hdrs.get("precedence") or "").strip().lower()
    if precedence in {"bulk", "list", "junk"}:
        return False, "bulk_precedence"

    # 5. Bounce header.
    if "x-failed-recipients" in hdrs:
        return False, "bounce_header"

    # 6. Bounce / auto-reply subject prefixes.
    if email.subject:
        subject_lower = email.subject.strip().lower()
        if any(subject_lower.startswith(p) for p in _BOUNCE_SUBJECT_PREFIXES):
            return False, "bounce_subject"

    # 7. Body has real content after we strip quoted history.
    stripped = strip_quoted_history(email.body_text or "")
    if len(stripped) < _MIN_BODY_CHARS_AFTER_QUOTE_STRIP:
        return False, "body_too_short"

    return True, None


__all__ = [
    "InboundEmail",
    "is_reply_worthy",
    "strip_quoted_history",
]
