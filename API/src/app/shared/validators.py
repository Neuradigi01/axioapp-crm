"""Cross-cutting input validators shared by API endpoints and CSV imports.

Pure functions — no DB access, no framework dependency. Each validator
returns the normalised value on success and raises `ValidationError` with
a human-readable `reason` on failure. The same reason strings are
mirrored in `app/src/app/shared/validators/custom-validators.ts` so form
errors and `errors.csv` rows read identically.

Rule matrix (locked in tasks/application-updates/step-1-shared-validators.md):

- name     letters / spaces / . - '        2–100 chars, trimmed
- email    RFC-lite, must have @ and .     max 254, lowercased on return
- phone    E.164-ish: optional +, 8–15 digits after stripping () - space
- password 8–128 chars with upper, lower, digit, special
- url      http(s):// only                  max 2048, non-empty host

The regex character classes are duplicated in the frontend counterpart;
`tests/shared/test_validators.py::test_frontend_backend_patterns_sync`
reads the TS source and asserts behavioural parity on a shared matrix
so the two sides can never silently drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Reason strings (mirrored verbatim in custom-validators.ts REASON)
# ---------------------------------------------------------------------------

REASON_REQUIRED_MISSING = "required field missing"
REASON_INVALID_EMAIL = "invalid email format"
REASON_INVALID_PHONE = "phone must be 8–15 digits (with optional country code)"
REASON_INVALID_NAME = "name contains disallowed characters"
REASON_WEAK_PASSWORD = "password must be 8–128 chars with upper, lower, digit, and special"
REASON_INVALID_URL = "invalid URL"


# ---------------------------------------------------------------------------
# Patterns (character classes match custom-validators.ts on the frontend)
# ---------------------------------------------------------------------------

NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ' .\-]{2,100}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^\+?[0-9]{8,15}$")
URL_RE = re.compile(r"^https?://[^\s]+$")

_PHONE_SEPARATORS_RE = re.compile(r"[\s()\-]")

EMAIL_MAX = 254
URL_MAX = 2048
PASSWORD_MIN = 8
PASSWORD_MAX = 128


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


@dataclass
class ValidationError(ValueError):
    """Raised by the validators when input fails a rule.

    Carries the human-readable `reason` for direct inclusion in an
    `ImportRowError` or an HTTP 4xx response body.
    """

    reason: str
    value: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.reason)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_name(value: str) -> str:
    """Return the trimmed name if it matches the allowed character set."""
    trimmed = (value or "").strip()
    if not NAME_RE.match(trimmed):
        raise ValidationError(REASON_INVALID_NAME, value=value)
    return trimmed


def validate_email(value: str) -> str:
    """Return the lowercased, trimmed email if it matches the RFC-lite shape."""
    trimmed = (value or "").strip()
    if len(trimmed) > EMAIL_MAX or not EMAIL_RE.match(trimmed):
        raise ValidationError(REASON_INVALID_EMAIL, value=value)
    return trimmed.lower()


def validate_phone(value: str) -> str:
    """Return the phone with separators stripped, matching optional + and 8–15 digits."""
    stripped = _PHONE_SEPARATORS_RE.sub("", value or "")
    if not PHONE_RE.match(stripped):
        raise ValidationError(REASON_INVALID_PHONE, value=value)
    return stripped


def validate_password_strength(value: str) -> None:
    """Raise if the password fails the length / character-class rules.

    Returns nothing on success — the caller already has the value; the
    hash is what gets persisted, not any normalised form.
    """
    if (
        not isinstance(value, str)
        or len(value) < PASSWORD_MIN
        or len(value) > PASSWORD_MAX
        or not re.search(r"[A-Z]", value)
        or not re.search(r"[a-z]", value)
        or not re.search(r"[0-9]", value)
        or not re.search(r"[^A-Za-z0-9]", value)
    ):
        raise ValidationError(REASON_WEAK_PASSWORD)


def validate_url(value: str) -> str:
    """Return the URL if it starts with http(s):// and parses to a non-empty host."""
    trimmed = (value or "").strip()
    if len(trimmed) > URL_MAX or not URL_RE.match(trimmed):
        raise ValidationError(REASON_INVALID_URL, value=value)
    try:
        parsed = urlparse(trimmed)
    except ValueError as exc:
        raise ValidationError(REASON_INVALID_URL, value=value) from exc
    if not parsed.netloc:
        raise ValidationError(REASON_INVALID_URL, value=value)
    return trimmed
