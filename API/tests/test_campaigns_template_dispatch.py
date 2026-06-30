"""Step 3.5.6 — template-aware dispatch + per-contact variable
resolution.

Pure unit tests on the helpers:

  1. `_resolve_template_variables` resolves `kind=static` verbatim.
  2. Resolves `kind=field` against contact attributes.
  3. Falls back to "Customer" when a field is empty (option (b)).
  4. Resolves `custom_data.<key>` from the JSONB column.
  5. `_preview_template_body` substitutes positionally for the inbox
     timeline text.

These are pure-Python tests — no DB, no Meta HTTP. The dispatch loop
itself is exercised end-to-end via the existing campaign tests + the
manual smoke test path; here we just lock down the resolution
contract that Step 3.5.6's branch depends on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.app.core.campaigns import service as campaigns_service
from src.app.core.campaigns.models import Campaign, CampaignStatus
from src.app.core.conversations.models import ConversationChannel
from src.app.core.integrations.whatsapp.models import WhatsAppTemplate

_ORG_ID = uuid.uuid4()


def _make_contact(
    *,
    full_name: str = "Asha Walker",
    phone: str | None = "+919876543210",
    email: str | None = "asha@example.com",
    custom_data: dict[str, Any] | None = None,
):
    """Build a Contact-shaped namespace — the helpers read attributes
    only, so a real ORM instance isn't required for unit tests."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        full_name=full_name,
        phone=phone,
        email=email,
        custom_data=custom_data or {},
    )


def _make_campaign_with_bindings(
    template_variables: dict[str, dict[str, str]] | None,
) -> Campaign:
    """Campaign with template_variables JSONB set to the given shape.
    Other columns are placeholders — the resolver reads only that
    column."""
    return Campaign(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        name="Test campaign",
        channel=ConversationChannel.whatsapp,
        audience_filter={},
        template=None,
        template_id=uuid.uuid4(),
        template_variables=template_variables,
        schedule_at=None,
        status=CampaignStatus.draft,
        created_by_id=uuid.uuid4(),
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


# --- _resolve_template_variables -----------------------------------------


class TestResolveTemplateVariables:
    def test_static_value_passes_through(self):
        campaign = _make_campaign_with_bindings({"1": {"kind": "static", "value": "30%"}})
        contact = _make_contact()
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {1: "30%"}

    def test_field_resolves_against_contact(self):
        campaign = _make_campaign_with_bindings(
            {
                "1": {"kind": "field", "value": "full_name"},
                "2": {"kind": "field", "value": "phone"},
                "3": {"kind": "field", "value": "email"},
            }
        )
        contact = _make_contact(
            full_name="Bob Verma",
            phone="+918888888888",
            email="bob@example.com",
        )
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {
            1: "Bob Verma",
            2: "+918888888888",
            3: "bob@example.com",
        }

    def test_empty_field_falls_back_to_customer(self):
        """Option (b) per Step 3.5.6: empty contact field → 'Customer'
        fallback rather than failing the message. Keeps delivery rate
        high; per-template fallback config is P2 work."""
        campaign = _make_campaign_with_bindings({"1": {"kind": "field", "value": "full_name"}})
        # NULL full_name (rare — contacts model has NOT NULL — but
        # could be empty string after a malformed import).
        contact = _make_contact(full_name="")
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {1: "Customer"}

    def test_missing_email_falls_back(self):
        campaign = _make_campaign_with_bindings({"1": {"kind": "field", "value": "email"}})
        contact = _make_contact(email=None)
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {1: "Customer"}

    def test_custom_data_field_resolves(self):
        campaign = _make_campaign_with_bindings(
            {"1": {"kind": "field", "value": "custom_data.preferred_sofa"}}
        )
        contact = _make_contact(custom_data={"preferred_sofa": "L-shaped"})
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {1: "L-shaped"}

    def test_custom_data_missing_falls_back(self):
        campaign = _make_campaign_with_bindings(
            {"1": {"kind": "field", "value": "custom_data.does_not_exist"}}
        )
        contact = _make_contact(custom_data={"other_key": "value"})
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {1: "Customer"}

    def test_mixed_static_and_field_resolution(self):
        """Real-world picker shape: header variable is the contact's
        name, body has a static discount + dynamic order id."""
        campaign = _make_campaign_with_bindings(
            {
                "1": {"kind": "field", "value": "full_name"},
                "2": {"kind": "static", "value": "30%"},
                "3": {"kind": "field", "value": "custom_data.order_id"},
            }
        )
        contact = _make_contact(
            full_name="Asha Walker",
            custom_data={"order_id": "ORD-9421"},
        )
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {1: "Asha Walker", 2: "30%", 3: "ORD-9421"}

    def test_empty_bindings_returns_empty_dict(self):
        """Zero-variable template (e.g. `hello_world`)."""
        campaign = _make_campaign_with_bindings({})
        contact = _make_contact()
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {}

    def test_none_bindings_returns_empty_dict(self):
        """Defensive: legacy campaign rows might have NULL template_variables."""
        campaign = _make_campaign_with_bindings(None)
        contact = _make_contact()
        out = campaigns_service._resolve_template_variables(campaign, contact)
        assert out == {}


# --- _preview_template_body ---------------------------------------------


class TestPreviewTemplateBody:
    def test_substitutes_positional_variables(self):
        template = WhatsAppTemplate(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=uuid.uuid4(),
            name="diwali_sale",
            language="en_US",
            category="MARKETING",
            status="APPROVED",
            body="Hi {{1}}, enjoy {{2}} off on all sofas this Diwali!",
            variable_count=2,
            last_synced_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        variables = {1: "Asha Walker", 2: "30%"}
        out = campaigns_service._preview_template_body(template, variables)
        assert out == ("Hi Asha Walker, enjoy 30% off on all sofas this Diwali!")

    def test_unfilled_placeholders_pass_through(self):
        """Defensive: if the picker somehow lets a `{{3}}` through
        without a binding, the preview leaves it intact rather than
        crashing."""
        template = WhatsAppTemplate(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=uuid.uuid4(),
            name="bogus",
            language="en_US",
            category="MARKETING",
            status="APPROVED",
            body="Hi {{1}}, your order {{3}} is ready.",
            variable_count=2,
            last_synced_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        variables = {1: "Bob"}
        out = campaigns_service._preview_template_body(template, variables)
        assert out == "Hi Bob, your order {{3}} is ready."

    def test_zero_variable_body_returned_verbatim(self):
        template = WhatsAppTemplate(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=uuid.uuid4(),
            name="hello_world",
            language="en_US",
            category="UTILITY",
            status="APPROVED",
            body="Welcome to our store.",
            variable_count=0,
            last_synced_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        out = campaigns_service._preview_template_body(template, {})
        assert out == "Welcome to our store."

    def test_empty_body_handled(self):
        """Defensive: malformed template with empty body returns ''."""
        template = WhatsAppTemplate(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=uuid.uuid4(),
            name="empty",
            language="en_US",
            category="UTILITY",
            status="APPROVED",
            body="",
            variable_count=0,
            last_synced_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        out = campaigns_service._preview_template_body(template, {})
        assert out == ""


# --- _get_contact_field --------------------------------------------------


class TestGetContactField:
    def test_known_field_returns_value(self):
        contact = _make_contact(full_name="Asha")
        assert campaigns_service._get_contact_field(contact, "full_name") == "Asha"

    def test_unknown_field_returns_empty(self):
        contact = _make_contact()
        assert campaigns_service._get_contact_field(contact, "unknown_xyz") == ""

    def test_custom_data_dot_notation(self):
        contact = _make_contact(custom_data={"loyalty_tier": "gold"})
        assert campaigns_service._get_contact_field(contact, "custom_data.loyalty_tier") == "gold"

    def test_custom_data_missing_key_returns_empty(self):
        contact = _make_contact(custom_data={})
        assert campaigns_service._get_contact_field(contact, "custom_data.x") == ""
