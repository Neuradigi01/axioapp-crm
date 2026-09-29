"""Store-profile format rules on `OrgSettingsPatch` (mirrored by the frontend form)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.app.core.settings.schemas import OrgSettingsPatch


def test_valid_store_profile_is_normalised() -> None:
    patch = OrgSettingsPatch(
        store_name="  Team Op  ",
        logo_url="https://teamop.com/logo.png",
        gst_number="29abcde1234f1z5",
        phone="+91 98765-43210",
        email="Store@TeamOp.com",
        postal_code="560001",
        currency="inr",
        tax_rate=Decimal("18.50"),
        timezone="Asia/Kolkata",
        locale="en-IN",
        city="   ",
    )
    assert patch.store_name == "Team Op"
    assert patch.gst_number == "29ABCDE1234F1Z5"
    assert patch.phone == "+919876543210"
    assert patch.email == "store@teamop.com"
    assert patch.currency == "INR"
    assert patch.city is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("store_name", "   "),
        ("logo_url", "teamop.com"),
        ("gst_number", "29ABCDE1234"),
        ("phone", "9876543210"),
        ("email", "not-an-email"),
        ("postal_code", "5"),
        ("currency", "RUPEES"),
        ("currency", None),
        ("tax_rate", Decimal("101")),
        ("tax_rate", Decimal("12.345")),
        ("timezone", "India"),
        ("timezone", "Mars/Olympus"),
        ("timezone", None),
        ("locale", "english"),
        ("locale", None),
    ],
)
def test_invalid_values_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as exc:
        OrgSettingsPatch(**{field: value})
    assert exc.value.errors()[0]["loc"] == (field,)


def test_unset_fields_stay_unset() -> None:
    """A PATCH that omits the required-when-sent fields never trips them."""
    patch = OrgSettingsPatch(store_name="Team Op")
    assert patch.model_dump(exclude_unset=True) == {"store_name": "Team Op"}
