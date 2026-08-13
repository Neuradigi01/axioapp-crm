"""Pure format validators for the Ask-* nodes
(``tasks/chatbot-builder`` Step 8).

No DB, no I/O — each function returns ``(is_valid, normalised_value)``.
On success ``normalised_value`` is the canonical form to persist
(``email.lower().strip()``, phone in E.164, ISO-8601 date, etc).
On failure ``normalised_value`` is the raw text so the retry-message
UX can quote it back.

Kept intentionally lightweight — a full ``phonenumbers`` library
would give better phone-normalisation but adds a dependency; the
E.164-shaped regex here covers the WhatsApp-first bot use case
(customers already text from a normalised MSISDN).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# --- Regex primitives -----------------------------------------------------

# RFC-5322 lite — quoted-string local parts and IDN not supported.
# Bot capture path prefers false-reject over false-accept.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$"
)

# E.164-shaped: optional +, 8-15 digits total, no separators.
_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")

_URL_RE = re.compile(
    r"^https?://[a-zA-Z0-9.-]+(?::\d+)?(?:/[^\s]*)?$"
)

# Common date shapes — ISO first, then DD/MM/YYYY, then MM/DD/YYYY.
_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
)

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


ValidationResult = tuple[bool, Any]


def validate_text(raw: str) -> ValidationResult:
    """Accepts any non-empty string. Trimmed."""
    v = (raw or "").strip()
    return (bool(v), v)


def validate_email(raw: str) -> ValidationResult:
    v = (raw or "").strip()
    if not v or not _EMAIL_RE.match(v):
        return (False, v)
    return (True, v.lower())


def validate_phone(raw: str) -> ValidationResult:
    v = (raw or "").strip()
    # Strip spaces, dashes, parens — WA users often paste
    # "+91 90000 00001" or "(415) 555-1234".
    cleaned = re.sub(r"[\s\-()]+", "", v)
    if not _PHONE_RE.match(cleaned):
        return (False, v)
    return (True, cleaned)


def validate_url(raw: str) -> ValidationResult:
    v = (raw or "").strip()
    if not v or not _URL_RE.match(v):
        return (False, v)
    return (True, v)


def validate_number(raw: str) -> ValidationResult:
    v = (raw or "").strip().replace(",", "")
    if not _NUMBER_RE.match(v):
        return (False, raw)
    return (True, float(v) if "." in v else int(v))


def validate_date(raw: str) -> ValidationResult:
    v = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(v, fmt).date()
            return (True, parsed.isoformat())
        except ValueError:
            continue
    return (False, raw)


def validate_choice(
    raw: str,
    *,
    choices: list[dict[str, Any]],
) -> ValidationResult:
    """Matches the customer's reply against a Pabbly-style choice
    list. Each choice is ``{value: <canonical>, aliases: [<str>, ...]}``.
    Case-insensitive exact match on value OR any alias; on match
    returns the canonical ``value``."""
    v = (raw or "").strip().lower()
    if not v:
        return (False, raw)
    for choice in choices:
        canonical = str(choice.get("value") or "").strip()
        if not canonical:
            continue
        candidates = [canonical.lower()]
        for alias in choice.get("aliases") or []:
            candidates.append(str(alias).strip().lower())
        if v in candidates:
            return (True, canonical)
    return (False, raw)


def resolve_validator(expected_format: str):  # type: ignore[no-untyped-def]
    """Return the validator fn for the given format. Returns
    :func:`validate_text` on unknown formats (fail-open — better to
    accept and let downstream nodes reject than to hard-block)."""
    return {
        "text": validate_text,
        "email": validate_email,
        "phone": validate_phone,
        "url": validate_url,
        "number": validate_number,
        "date": validate_date,
    }.get(expected_format, validate_text)


__all__ = [
    "ValidationResult",
    "resolve_validator",
    "validate_choice",
    "validate_date",
    "validate_email",
    "validate_number",
    "validate_phone",
    "validate_text",
    "validate_url",
]
