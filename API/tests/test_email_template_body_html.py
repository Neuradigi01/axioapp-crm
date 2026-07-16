"""Campaigns v1 Step 04 — schema-layer invariants for body_html on
Email templates + campaigns.

Pure Pydantic validation — no DB. Full DB round-trip coverage lands
with the browser smoke on Ajay's Workspace (per repo memory the
pytest suite runs ~12 min so we lean on schema tests for fast
feedback on the branching invariants).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from src.app.core.campaigns.schemas import CampaignCreate
from src.app.core.templates.schemas import TemplateCreate


def _base_template(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "monthly_newsletter",
        "channel": "email",
        "body_text": "Hi {{first_name}}, this month...",
        "subject": "Your monthly deals",
    }
    base.update(overrides)
    return base


class TestTemplateBodyHtml:
    def test_email_body_text_only_still_works(self):
        # Backwards compat — pre-Step-04 email templates only had
        # body_text and must keep parsing.
        payload = TemplateCreate.model_validate(_base_template())
        assert payload.body_text.startswith("Hi ")
        assert payload.body_html is None
        assert payload.body_text_fallback_auto is True

    def test_email_body_html_only(self):
        # Operator authored HTML but left body_text empty; service will
        # auto-derive the plain fallback.
        payload = TemplateCreate.model_validate(
            _base_template(body_text=None, body_html="<p>Hi {{first_name}}</p>"),
        )
        assert payload.body_html == "<p>Hi {{first_name}}</p>"

    def test_email_both_bodies_supplied(self):
        payload = TemplateCreate.model_validate(
            _base_template(
                body_text="Hi {{first_name}}, plain",
                body_html="<p>Hi {{first_name}}, rich</p>",
            ),
        )
        assert payload.body_text.startswith("Hi ")
        assert payload.body_html is not None

    def test_email_neither_body_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreate.model_validate(_base_template(body_text=None, body_html=None))
        assert "body_text or body_html" in str(exc.value)

    def test_email_body_text_empty_string_treated_as_missing(self):
        with pytest.raises(ValidationError):
            TemplateCreate.model_validate(_base_template(body_text="   ", body_html=None))

    def test_email_subject_still_required(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreate.model_validate(_base_template(subject=None))
        assert "subject is required" in str(exc.value)

    def test_whatsapp_rejects_body_html(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreate.model_validate(
                {
                    "name": "welcome",
                    "channel": "whatsapp",
                    "body_text": "Hi {{1}}",
                    "body_html": "<p>Hi {{1}}</p>",
                }
            )
        assert "body_html is only valid for email templates" in str(exc.value)

    def test_whatsapp_requires_body_text(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreate.model_validate(
                {
                    "name": "welcome",
                    "channel": "whatsapp",
                    "body_text": None,
                }
            )
        assert "body_text is required for non-email" in str(exc.value)

    def test_fallback_auto_defaults_true(self):
        payload = TemplateCreate.model_validate(_base_template())
        assert payload.body_text_fallback_auto is True

    def test_fallback_auto_can_be_disabled(self):
        payload = TemplateCreate.model_validate(
            _base_template(body_text_fallback_auto=False),
        )
        assert payload.body_text_fallback_auto is False

    def test_body_html_length_capped(self):
        # 200_000-char ceiling — anything larger is rejected.
        with pytest.raises(ValidationError):
            TemplateCreate.model_validate(
                _base_template(body_html="<p>" + ("x" * 200_000) + "</p>"),
            )


def _base_campaign(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "July newsletter",
        "channel": "email",
        "email_account_id": str(uuid.uuid4()),
        "sender_name": "Your Shop",
        "subject": "July deals",
        "body_html": "<p>Hi {{first_name}}, deals inside.</p>",
    }
    base.update(overrides)
    return base


class TestCampaignBodyHtml:
    def test_email_campaign_with_body_html_accepted(self):
        payload = CampaignCreate.model_validate(_base_campaign())
        assert payload.body_html is not None
        assert payload.template is None
        assert payload.template_id is None

    def test_email_campaign_body_html_and_template_rejected(self):
        # exactly-one guard fires.
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(
                _base_campaign(template="Free-text body override"),
            )
        assert "exactly one" in str(exc.value).lower()

    def test_email_campaign_body_html_and_template_id_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(
                _base_campaign(template_id=str(uuid.uuid4())),
            )
        assert "exactly one" in str(exc.value).lower()

    def test_whatsapp_campaign_rejects_body_html(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(
                {
                    "name": "diwali",
                    "channel": "whatsapp",
                    "template": "Diwali offers for {{full_name}}",
                    "body_html": "<p>Diwali offers</p>",
                }
            )
        assert "body_html is only valid for email campaigns" in str(exc.value)

    def test_email_campaign_with_template_id_still_works(self):
        # Existing Step 3.5 flow unbroken.
        payload = CampaignCreate.model_validate(
            _base_campaign(template_id=str(uuid.uuid4()), body_html=None),
        )
        assert payload.template_id is not None
        assert payload.body_html is None

    def test_email_campaign_no_source_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(_base_campaign(body_html=None))
        assert "Provide" in str(exc.value)

    def test_email_body_html_length_capped(self):
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(
                _base_campaign(body_html="<p>" + ("x" * 200_000) + "</p>"),
            )
