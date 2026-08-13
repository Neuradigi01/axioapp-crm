"""Ask-* node tests — pure Python, no DB / live send.

Covers validators + parsers + registration. Full save-target write
+ resume/retry/timeout DB tests live in
``test_ask_nodes_db.py`` — deferred to batch pytest per memory
``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.app.core.chatbots.engine import NODE_REGISTRY
from src.app.core.chatbots.nodes.ask_address import _parse_address
from src.app.core.chatbots.nodes.ask_location import _LAT_LNG_RE
from src.app.core.chatbots.validators import (
    resolve_validator,
    validate_choice,
    validate_date,
    validate_email,
    validate_number,
    validate_phone,
    validate_text,
    validate_url,
)


# --- Registry side-effect --------------------------------------------------


def test_all_ask_nodes_registered() -> None:
    for t in ("ask_question", "ask_address", "ask_location", "ask_media"):
        assert t in NODE_REGISTRY, f"node '{t}' not registered"


# --- Validators -----------------------------------------------------------


def test_validate_text_trims_and_accepts_nonempty() -> None:
    assert validate_text("  hello  ") == (True, "hello")
    assert validate_text("") == (False, "")
    assert validate_text(None) == (False, "")  # type: ignore[arg-type]


def test_validate_email_valid_and_normalises_lower() -> None:
    assert validate_email("Alex@Example.COM") == (True, "alex@example.com")
    assert validate_email("bad-email") == (False, "bad-email")
    assert validate_email("no@dot") == (False, "no@dot")


def test_validate_phone_accepts_e164_and_pretty_formats() -> None:
    ok, val = validate_phone("+91 90000 00001")
    assert ok is True and val == "+919000000001"

    ok, val = validate_phone("(415) 555-1234")
    assert ok is True and val == "4155551234"

    ok, val = validate_phone("123")
    assert ok is False


def test_validate_url_https_only_here() -> None:
    assert validate_url("https://example.com/path")[0] is True
    assert validate_url("http://example.com")[0] is True
    assert validate_url("ftp://example.com")[0] is False
    assert validate_url("not a url")[0] is False


def test_validate_number_int_and_float_and_thousands_separator() -> None:
    assert validate_number("42") == (True, 42)
    assert validate_number("3.14") == (True, 3.14)
    assert validate_number("1,234") == (True, 1234)
    assert validate_number("abc")[0] is False


def test_validate_date_multiple_shapes() -> None:
    assert validate_date("2026-08-13") == (True, "2026-08-13")
    assert validate_date("13/08/2026") == (True, "2026-08-13")
    assert validate_date("13-08-2026") == (True, "2026-08-13")
    assert validate_date("not a date")[0] is False


def test_validate_choice_matches_value_or_aliases() -> None:
    choices = [
        {"value": "yes", "aliases": ["y", "yep", "sure"]},
        {"value": "no", "aliases": ["n", "nope"]},
    ]
    assert validate_choice("yes", choices=choices) == (True, "yes")
    assert validate_choice("YEP", choices=choices) == (True, "yes")
    assert validate_choice("nope", choices=choices) == (True, "no")
    assert validate_choice("maybe", choices=choices)[0] is False


def test_resolve_validator_maps_known_formats() -> None:
    assert resolve_validator("email") is validate_email
    assert resolve_validator("phone") is validate_phone
    assert resolve_validator("number") is validate_number
    assert resolve_validator("date") is validate_date
    assert resolve_validator("url") is validate_url
    # Unknown format falls back to text (fail-open).
    assert resolve_validator("hieroglyphics") is validate_text


# --- Address parser -------------------------------------------------------


def test_parse_address_us_zip_detected() -> None:
    result = _parse_address("742 Evergreen Terrace, Springfield, IL 62704, USA")
    assert result["postal_code"] == "62704"
    assert result["country"] == "US"
    assert result["street"] == "742 Evergreen Terrace"
    assert result["city"] == "Springfield"


def test_parse_address_in_pin() -> None:
    result = _parse_address("14 MG Road, Bangalore, KA, 560001, India")
    assert result["postal_code"] == "560001"
    assert result["country"] == "IN"


def test_parse_address_uk_postcode() -> None:
    result = _parse_address("221B Baker Street, London, NW1 6XE, UK")
    assert result.get("country") == "GB"
    assert "postal_code" in result


def test_parse_address_free_form_preserves_raw() -> None:
    result = _parse_address("just some free-form text nothing structured")
    assert result["raw"] == "just some free-form text nothing structured"
    # No postal_code inferred.
    assert "postal_code" not in result


# --- Location regex -------------------------------------------------------


def test_lat_lng_regex_matches_comma_pair() -> None:
    m = _LAT_LNG_RE.search("12.9716, 77.5946")
    assert m is not None
    assert float(m.group(1)) == pytest.approx(12.9716)
    assert float(m.group(2)) == pytest.approx(77.5946)


def test_lat_lng_regex_matches_no_space() -> None:
    m = _LAT_LNG_RE.search("12.9716,77.5946")
    assert m is not None


def test_lat_lng_regex_matches_negative() -> None:
    m = _LAT_LNG_RE.search("-33.8688, 151.2093")
    assert m is not None
    assert float(m.group(1)) == pytest.approx(-33.8688)


# --- Handler-level rejections --------------------------------------------


@pytest.mark.asyncio
async def test_ask_question_rejects_missing_prompt() -> None:
    from src.app.core.chatbots.nodes.ask_question import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            conversation_id=None,
            contact_id=None,
            lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="ask_question",
        node_config={"save_to": "contact.full_name"},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "prompt" in result.error.lower()


@pytest.mark.asyncio
async def test_ask_question_rejects_missing_save_to() -> None:
    from src.app.core.chatbots.nodes.ask_question import handle

    fake_ctx = SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            conversation_id=None,
            contact_id=None,
            lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="n1",
        node_type="ask_question",
        node_config={"prompt": "hi"},
        run_context={},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "save_to" in result.error.lower()


# --- Placeholder-contact helper --------------------------------------------


def test_placeholder_contact_helper_exists() -> None:
    """Guardrail — the matcher / adapter chain will import this
    helper in a follow-up wiring. Rename breaks that; catch here."""
    from src.app.core.contacts.service import get_or_create_placeholder_contact

    assert callable(get_or_create_placeholder_contact)
