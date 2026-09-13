"""Email threading helpers for AI auto-replies
(``tasks/ai-assistants-omnichannel`` Step 6).

Pure functions the future email-outbound path (currently deferred
alongside the ``ChannelContext`` refactor) will call to shape the
``Re:`` subject, the ``In-Reply-To`` / ``References`` headers, and
the quoted body divider. Landed in Step 6 so the tests + logic are
in place and the eventual send-side wire-up is trivial (one function
call per header + one for the body).

Deliberately RFC 5322 / RFC 2822-compliant on the header side;
the body-quoting divider matches common client (Gmail / Outlook)
conventions so replies visually thread inside the customer's client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Matches leading "Re:", "RE:", "re :", "Re: Re: RE:" — collapses the
# whole run to a single canonical "Re: " prefix. Only English "Re" in
# v1; RFC 5322 also permits "Fwd:" / "Aw:" / "Sv:" but we don't yet
# have a per-locale reason to complicate this.
_RE_PREFIX_RE = re.compile(r"^\s*(?:re\s*:\s*)+", re.IGNORECASE)


def reply_subject(inbound_subject: str | None) -> str:
    """Return the ``Subject:`` for the outbound AI reply.

    ``Question about pricing`` → ``Re: Question about pricing``
    ``Re: Question about pricing`` → ``Re: Question about pricing`` (idempotent)
    ``Re: Re: RE: Question`` → ``Re: Question`` (collapses runs)
    ``None`` / empty → ``Re: (no subject)`` (mail clients unhappy with empty)
    """
    if not inbound_subject or not inbound_subject.strip():
        return "Re: (no subject)"
    stripped = _RE_PREFIX_RE.sub("", inbound_subject).strip()
    if not stripped:
        return "Re: (no subject)"
    return f"Re: {stripped}"


def references_chain(
    inbound_references: str | None,
    inbound_message_id: str | None,
) -> str | None:
    """Build the outbound ``References:`` chain. RFC 5322: the chain
    is the inbound's own References (or absent) with the inbound's
    ``Message-ID`` appended so the outbound sits at the tail.

    Returns None when the inbound had no ``Message-ID`` (some
    machine-generated mail omits it). Callers should skip the header
    entirely in that case rather than send an empty chain."""
    if not inbound_message_id:
        return inbound_references or None
    chain: list[str] = []
    if inbound_references:
        # Existing chain is space-separated, angle-bracketed ids.
        # Preserve as-is; splitting + rejoining would reflow whitespace
        # that some mail systems check byte-for-byte.
        chain.append(inbound_references.strip())
    chain.append(inbound_message_id.strip())
    return " ".join(chain)


@dataclass(frozen=True, slots=True)
class ReplyThread:
    """Bundle of the four fields the outbound sender needs. Callers
    build one from the inbound envelope + AI reply text and hand the
    whole thing to the send adapter — no chance of accidentally
    forgetting one of them."""

    subject: str
    body: str
    in_reply_to: str | None
    references: str | None


def build_reply_thread(
    *,
    ai_reply_text: str,
    inbound_subject: str | None,
    inbound_message_id: str | None,
    inbound_references: str | None,
    inbound_body_text: str,  # noqa: ARG001 — kept for API stability; threading now header-only
) -> ReplyThread:
    """Compose the outbound envelope for an AI reply.

    Threading is header-only (``In-Reply-To`` + ``References``) —
    modern mail clients (Gmail / Outlook / Apple Mail) collapse
    conversations on those alone, so we no longer append the inbound
    body under a ``--- Original message ---`` divider. Reasons:

      * The CRM stores the outbound body verbatim in ``tbl_messages``
        and paints it as a chat bubble. The quoted block was rendering
        as literal ``> Hello CRM How are you?`` text inside the bubble,
        immediately below the customer's own bubble — visual duplication
        of a message already on screen.
      * Real inboxes still thread correctly by RFC 5322 headers alone,
        which we've been sending since Step 6.
    """
    subject = reply_subject(inbound_subject)
    references = references_chain(inbound_references, inbound_message_id)
    body = ai_reply_text.rstrip()
    return ReplyThread(
        subject=subject,
        body=body,
        in_reply_to=inbound_message_id.strip() if inbound_message_id else None,
        references=references,
    )


__all__ = [
    "ReplyThread",
    "build_reply_thread",
    "references_chain",
    "reply_subject",
]
