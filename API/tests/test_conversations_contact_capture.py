"""WhatsApp sender → contact capture.

Pure-function coverage (no DB) for:

* ``_profile_name`` — pulls the sender's WhatsApp profile name out of a
  Cloud API webhook ``value`` block;
* ``ConversationContactSet`` — the details-rail save / link payload
  accepts exactly one of ``contact_id`` / ``full_name``;
* ``_is_placeholder_name`` — only auto-generated names are replaceable.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.app.core.conversations.adapters.whatsapp import _profile_name
from src.app.core.conversations.schemas import ConversationContactSet
from src.app.core.conversations.service import _is_placeholder_name


def test_profile_name_matches_sender_wa_id() -> None:
    value = {
        "contacts": [
            {"wa_id": "911111111111", "profile": {"name": "Someone Else"}},
            {"wa_id": "918956346287", "profile": {"name": "  Ajay Gogane  "}},
        ]
    }
    assert _profile_name(value, "918956346287") == "Ajay Gogane"


def test_profile_name_falls_back_to_first_contact() -> None:
    value = {"contacts": [{"wa_id": "other", "profile": {"name": "Asha"}}]}
    assert _profile_name(value, "918956346287") == "Asha"


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"contacts": "not-a-list"},
        {"contacts": [{"wa_id": "9189", "profile": {}}]},
        {"contacts": [{"wa_id": "9189", "profile": {"name": "   "}}]},
        {"contacts": [{"wa_id": "9189", "profile": {"name": 42}}]},
    ],
)
def test_profile_name_absent_or_blank_is_none(value: dict) -> None:
    assert _profile_name(value, "9189") is None


def test_profile_name_truncated_to_column_width() -> None:
    value = {"contacts": [{"wa_id": "9189", "profile": {"name": "x" * 300}}]}
    assert _profile_name(value, "9189") == "x" * 255


def test_contact_set_accepts_exactly_one_field() -> None:
    assert ConversationContactSet(full_name="  Ajay ").full_name == "Ajay"
    cid = uuid.uuid4()
    assert ConversationContactSet(contact_id=cid).contact_id == cid
    with pytest.raises(ValidationError):
        ConversationContactSet()
    with pytest.raises(ValidationError):
        ConversationContactSet(contact_id=cid, full_name="Ajay")
    with pytest.raises(ValidationError):
        ConversationContactSet(full_name="   ")


@pytest.mark.parametrize(
    ("full_name", "phone", "expected"),
    [
        ("Unknown WhatsApp contact", "+918956346287", True),
        ("+918956346287", "+918956346287", True),
        ("", "+918956346287", True),
        ("Ajay", "+918956346287", False),
    ],
)
def test_is_placeholder_name(full_name: str, phone: str, expected: bool) -> None:
    contact = SimpleNamespace(full_name=full_name, phone=phone)
    assert _is_placeholder_name(contact) is expected  # type: ignore[arg-type]
