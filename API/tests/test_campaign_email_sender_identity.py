"""Campaigns v1 Step 03 — Email sender identity + subject + preheader.

Two groups:

  1. ``CampaignCreate`` schema validation. Pure Pydantic — no DB. Covers
     the ``_email_channel_requires_sender_and_subject`` model validator
     against every "missing X" branch, plus the WhatsApp control case
     (no ripple onto other channels).

  2. ``_resolve_email_sender`` service helper against a fake
     ``AsyncSession`` stand-in (same pattern as ``test_email_accounts``).
     Covers the four outcomes: happy path, unknown id, cross-org id,
     unverified mailbox.

Full DB-round-trip integration coverage lands with the browser smoke on
Ajay's Workspace (per repo memory — pytest suite takes ~12 min so we
batch expensive fixtures and lean on the schema + fake-session tests
for fast feedback on the invariants).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from src.app.core.campaigns.schemas import CampaignCreate
from src.app.core.campaigns.service import _resolve_email_sender
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)


def _valid_email_payload(**overrides: Any) -> dict[str, Any]:
    """Minimal valid Email CampaignCreate payload — the picker sends one
    of these when the operator has filled all required Email fields."""
    base: dict[str, Any] = {
        "name": "July newsletter",
        "channel": "email",
        "template": "Hi {{first_name}}, this month…",
        "email_account_id": str(uuid.uuid4()),
        "sender_name": "Your Shop",
        "reply_to": "hello@yourshop.com",
        "subject": "Your monthly deals, {{first_name}} 🎁",
        "preheader": "Five picks for you, expires Sunday midnight",
    }
    base.update(overrides)
    return base


class TestCampaignCreateEmailSchema:
    """Pure Pydantic — no DB."""

    def test_valid_email_payload_passes(self):
        payload = CampaignCreate.model_validate(_valid_email_payload())
        assert payload.channel.value == "email"
        assert payload.sender_name == "Your Shop"
        assert payload.subject.startswith("Your monthly deals")
        # Reply-to is normalised as EmailStr — should still round-trip
        # to the same string.
        assert str(payload.reply_to) == "hello@yourshop.com"
        assert payload.preheader == "Five picks for you, expires Sunday midnight"

    def test_missing_email_account_id_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(_valid_email_payload(email_account_id=None))
        assert "email_account_id" in str(exc.value)

    def test_missing_sender_name_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(_valid_email_payload(sender_name=None))
        assert "sender_name" in str(exc.value)

    def test_missing_subject_rejected(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(_valid_email_payload(subject=None))
        assert "subject" in str(exc.value)

    def test_multiple_missing_fields_listed_together(self):
        with pytest.raises(ValidationError) as exc:
            CampaignCreate.model_validate(
                _valid_email_payload(email_account_id=None, sender_name=None, subject=None),
            )
        msg = str(exc.value)
        assert "email_account_id" in msg
        assert "sender_name" in msg
        assert "subject" in msg

    def test_reply_to_optional(self):
        """Reply-to falls back to the mailbox address at dispatch time
        (Step 05). Schema keeps it optional."""
        payload = CampaignCreate.model_validate(_valid_email_payload(reply_to=None))
        assert payload.reply_to is None

    def test_preheader_optional(self):
        payload = CampaignCreate.model_validate(_valid_email_payload(preheader=None))
        assert payload.preheader is None

    def test_invalid_reply_to_rejected(self):
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(_valid_email_payload(reply_to="not-an-email"))

    def test_subject_length_capped(self):
        # RFC 5322 line-length hard limit is 998 — payload with 999 is
        # over the schema's max_length.
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(_valid_email_payload(subject="x" * 999))

    def test_whatsapp_still_works_without_email_fields(self):
        """WA campaigns must NOT be forced to send email_account_id etc —
        the required-when-Email guard branches on channel."""
        payload = CampaignCreate.model_validate(
            {
                "name": "Diwali sale",
                "channel": "whatsapp",
                "template": "Diwali offers for {{full_name}}",
            }
        )
        assert payload.channel.value == "whatsapp"
        assert payload.email_account_id is None
        assert payload.sender_name is None
        assert payload.subject is None


# --- _resolve_email_sender ---------------------------------------------


def _make_account(*, org_id: uuid.UUID, sync_state: EmailAccountSyncState) -> EmailAccount:
    """Builds an EmailAccount without touching the DB — the field set
    matches the ORM class so the service function can read `org_id`
    and `sync_state` off the returned row."""
    return EmailAccount(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        provider=EmailAccountProvider.gmail,
        external_account_id="ext-1",
        email_address="sales@yourshop.com",
        display_name="Your Shop",
        access_token_enc="enc",
        refresh_token_enc="enc",
        scopes_granted=[],
        sync_state=sync_state,
        daily_sent_count=0,
    )


class _StubSession:
    """AsyncSession stand-in — only the paths the DAL uses. We drive
    the lookup by pre-loading a row and letting ``execute`` return it
    via the same ``.scalar_one_or_none()`` shape SQLAlchemy uses."""

    def __init__(self, *, account: EmailAccount | None):
        self._account = account

    async def execute(self, _stmt):  # noqa: ANN001 — SQL stmt opaque here
        stub = _StubSession
        # Return a result object whose scalar_one_or_none returns the
        # pre-loaded account (or None to simulate "not found / hidden
        # by RLS").
        return _StubResult(self._account)


class _StubResult:
    def __init__(self, row: EmailAccount | None):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class TestResolveEmailSender:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        org = uuid.uuid4()
        account = _make_account(org_id=org, sync_state=EmailAccountSyncState.live)
        session = _StubSession(account=account)
        out = await _resolve_email_sender(session, org_id=org, account_id=account.id)
        assert out is account

    @pytest.mark.asyncio
    async def test_missing_mailbox_400(self):
        from fastapi import HTTPException

        session = _StubSession(account=None)
        with pytest.raises(HTTPException) as exc:
            await _resolve_email_sender(
                session,
                org_id=uuid.uuid4(),
                account_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 400
        assert "not found" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_cross_org_mailbox_400(self):
        from fastapi import HTTPException

        # Account belongs to another org — RLS usually hides these but
        # our belt-and-suspenders check catches any leak.
        wrong_org = uuid.uuid4()
        account = _make_account(org_id=wrong_org, sync_state=EmailAccountSyncState.live)
        session = _StubSession(account=account)
        with pytest.raises(HTTPException) as exc:
            await _resolve_email_sender(
                session,
                org_id=uuid.uuid4(),
                account_id=account.id,
            )
        assert exc.value.status_code == 400
        assert "not found" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_disconnected_mailbox_400(self):
        from fastapi import HTTPException

        org = uuid.uuid4()
        account = _make_account(org_id=org, sync_state=EmailAccountSyncState.disconnected)
        session = _StubSession(account=account)
        with pytest.raises(HTTPException) as exc:
            await _resolve_email_sender(session, org_id=org, account_id=account.id)
        assert exc.value.status_code == 400
        assert "not connected" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_erroring_mailbox_400(self):
        from fastapi import HTTPException

        org = uuid.uuid4()
        account = _make_account(org_id=org, sync_state=EmailAccountSyncState.error)
        session = _StubSession(account=account)
        with pytest.raises(HTTPException) as exc:
            await _resolve_email_sender(session, org_id=org, account_id=account.id)
        assert exc.value.status_code == 400
        assert "not connected" in exc.value.detail.lower()
