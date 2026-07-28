"""Unit coverage for `src.app.shared.validators` + the FE/BE regex-sync guard.

The five format validators (name / email / phone / password / URL) are
each exercised against an accept list and a reject list. The sync guard
reads `app/src/app/shared/validators/custom-validators.ts` from disk,
extracts the regex source strings the frontend uses, compiles them
under Python's `re`, and asserts they produce identical accept / reject
answers on a shared matrix — so an edit on one side that breaks parity
lights up here immediately, without any Karma round-trip.

Test file lives under `api/tests/shared/` alongside the other shared
utility tests (bulk_action_schemas, get_or_404, pagination, …).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.app.shared import import_errors, validators
from src.app.shared.validators import (
    EMAIL_RE,
    NAME_RE,
    PHONE_RE,
    URL_RE,
    ValidationError,
    validate_email,
    validate_name,
    validate_password_strength,
    validate_phone,
    validate_url,
)


# ---------------------------------------------------------------------------
# validate_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "John",
        "Mary-Jane",
        "O'Neil",
        "Jean-Luc Picard",
        "Renée",
        "Dr. Smith",
        "  John  ",  # trimmed
    ],
)
def test_validate_name_accepts_real_names(value: str) -> None:
    assert validate_name(value) == value.strip()


@pytest.mark.parametrize(
    "value",
    ["John123", "😀", "<script>", "J", "A@B", "  ", ""],
)
def test_validate_name_rejects_bad(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_name(value)
    assert exc.value.reason == validators.REASON_INVALID_NAME


# ---------------------------------------------------------------------------
# validate_email
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("user@example.com", "user@example.com"),
        ("User+Tag@Ex.CO", "user+tag@ex.co"),
        ("  a.b@c.d  ", "a.b@c.d"),
    ],
)
def test_validate_email_accepts_and_lowercases(value: str, expected: str) -> None:
    assert validate_email(value) == expected


@pytest.mark.parametrize(
    "value",
    ["test@", "@example.com", "no-at.com", "a b@x.com", ""],
)
def test_validate_email_rejects_bad(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_email(value)
    assert exc.value.reason == validators.REASON_INVALID_EMAIL


def test_validate_email_rejects_too_long() -> None:
    over = "a" * 250 + "@x.co"  # 255 chars
    with pytest.raises(ValidationError):
        validate_email(over)


# ---------------------------------------------------------------------------
# validate_phone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("9876543210", "9876543210"),          # bare 10-digit mobile
        ("+91 98765 43210", "9876543210"),     # +91 prefix, spaces
        ("91-9876543210", "9876543210"),       # 91 prefix, dash
        ("+919876543210", "9876543210"),       # +91 no separators
        ("(987) 654-3210", "9876543210"),      # US-style separators, still Indian
        ("6234567890", "6234567890"),          # mobile starting with 6
        ("7234567890", "7234567890"),          # 7
        ("8234567890", "8234567890"),          # 8
    ],
)
def test_validate_phone_accepts_and_strips(value: str, expected: str) -> None:
    assert validate_phone(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "abc",                    # non-digits
        "1234567",                # too short
        "5234567890",             # starts with 5 — not an Indian mobile prefix
        "0987654321",             # leading zero
        "12345678901",            # 11 digits, no valid prefix
        "+1 415 555 0132",        # US number
        "020-79460958",           # Delhi landline (0 prefix, 11 digits total)
        "",                       # empty
    ],
)
def test_validate_phone_rejects_bad(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_phone(value)
    assert exc.value.reason == validators.REASON_INVALID_PHONE


# ---------------------------------------------------------------------------
# validate_password_strength
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["Passw0rd!", "Xy9!zzzz", "Longer#One1"],
)
def test_validate_password_strength_accepts(value: str) -> None:
    validate_password_strength(value)  # no return; no raise


@pytest.mark.parametrize(
    "value",
    [
        "password",         # no upper, no digit, no special
        "PASSWORD1!",       # no lower
        "passw0rd!",        # no upper
        "Password!",        # no digit
        "Password1",        # no special
        "Pw1!",             # too short
        "a" * 129 + "A1!",  # too long
        "",
    ],
)
def test_validate_password_strength_rejects(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_password_strength(value)
    assert exc.value.reason == validators.REASON_WEAK_PASSWORD


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["https://example.com", "http://x.co/y?z=1", "  https://a.b  "],
)
def test_validate_url_accepts(value: str) -> None:
    assert validate_url(value) == value.strip()


@pytest.mark.parametrize(
    "value",
    ["example.com", "ftp://x.co", "https://", "   ", ""],
)
def test_validate_url_rejects(value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_url(value)
    assert exc.value.reason == validators.REASON_INVALID_URL


# ---------------------------------------------------------------------------
# import_errors.write_errors_csv
# ---------------------------------------------------------------------------


def test_write_errors_csv_shape() -> None:
    headers = ["full_name", "phone", "email"]
    rows = [
        {"full_name": "Alice", "phone": "9876543210", "email": "a@x.co"},
        {"full_name": "", "phone": "9876543211", "email": "b@x.co"},
        {"full_name": "😀", "phone": "9876543212", "email": "c@x.co"},
    ]
    errs = [
        import_errors.ImportRowError(
            row_number=2, column="full_name", value="", reason="required field missing"
        ),
        import_errors.ImportRowError(
            row_number=3,
            column="full_name",
            value="😀",
            reason="name contains disallowed characters",
        ),
    ]

    out = import_errors.write_errors_csv(headers, rows, errs).decode("utf-8")
    lines = out.strip().splitlines()

    assert lines[0] == "full_name,phone,email,__row_number,__column,__value,__error_reason"
    assert lines[1] == ',9876543211,b@x.co,2,full_name,,required field missing'
    assert lines[2] == '😀,9876543212,c@x.co,3,full_name,😀,name contains disallowed characters'


# ---------------------------------------------------------------------------
# FE / BE regex-sync guard
# ---------------------------------------------------------------------------


_FRONTEND_FILE = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "src"
    / "app"
    / "shared"
    / "validators"
    / "custom-validators.ts"
)


def _extract_frontend_source(name: str) -> str:
    """Read `export const <NAME>_RE_SRC = '...';` from the TS file."""
    text = _FRONTEND_FILE.read_text(encoding="utf-8")
    m = re.search(
        rf"export const {re.escape(name)}_RE_SRC\s*=\s*(['\"])(?P<pat>.*?)\1;",
        text,
    )
    assert m, f"could not find {name}_RE_SRC in {_FRONTEND_FILE}"
    # TS single-quoted strings escape `\\` as `\\\\`; normalise back to a
    # single backslash so the string can be re-compiled by Python `re`.
    return m.group("pat").encode("utf-8").decode("unicode_escape")


@pytest.mark.parametrize(
    "name,backend_re,samples",
    [
        (
            "NAME",
            NAME_RE,
            [
                ("John", True),
                ("Mary-Jane", True),
                ("O'Neil", True),
                ("Renée", True),
                ("Dr. Smith", True),
                ("John123", False),
                ("😀", False),
                ("<script>", False),
                ("J", False),
                ("", False),
            ],
        ),
        (
            "EMAIL",
            EMAIL_RE,
            [
                ("user@example.com", True),
                ("user+tag@ex.co", True),
                ("test@", False),
                ("@example.com", False),
                ("no-at.com", False),
                ("a b@x.com", False),
            ],
        ),
        (
            "PHONE",
            PHONE_RE,
            [
                # Phone samples are POST-strip — the strip step is the same on
                # both sides, so testing the compiled regex is enough.
                ("9876543210", True),          # bare 10-digit mobile
                ("+919876543210", True),       # +91 prefix
                ("919876543210", True),        # 91 prefix
                ("6234567890", True),          # first digit 6
                ("abc", False),
                ("5234567890", False),         # starts with 5 — not an Indian mobile
                ("+14155550132", False),       # US number
                ("1234567", False),            # too short
                ("12345678901", False),        # 11 digits
            ],
        ),
        (
            "URL",
            URL_RE,
            [
                ("https://example.com", True),
                ("http://x.co/y?z=1", True),
                ("example.com", False),
                ("ftp://x.co", False),
            ],
        ),
    ],
)
def test_frontend_backend_patterns_sync(
    name: str,
    backend_re: re.Pattern[str],
    samples: list[tuple[str, bool]],
) -> None:
    """Compile the FE regex under Python `re` and assert parity with the BE regex."""
    fe_re = re.compile(_extract_frontend_source(name))
    for value, expected in samples:
        assert bool(fe_re.match(value)) is expected, (
            f"FE {name}_RE mismatch on {value!r}: expected {expected}"
        )
        assert bool(backend_re.match(value)) is expected, (
            f"BE {name}_RE mismatch on {value!r}: expected {expected}"
        )
