"""Tests for Step 20's billing-email pipeline.

Coverage:
  - Every template renders to non-empty subject/HTML/text under a
    minimum context.
  - `send_billing_email` resolves the org's Owner-equivalent member,
    renders, and hands the result to `get_email_backend()`.
  - Missing Owner → log + return; no exception, no email dispatched.
  - Unknown template key → log + return.
  - Backend failure → swallowed; caller's parent flow unaffected.

The email backend is monkeypatched to a capture spy so tests assert
on `Email` payloads without touching SMTP.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import (
    Permission,
    Role,
    RolePermission,
)
from src.app.core.subscriptions.email_templates import RENDERERS, render
from src.app.core.subscriptions.notifications import send_billing_email
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember
from src.app.shared.email import Email
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo
from src.models.user import UserLogin

# ---------------------------------------------------------------------------
# Spy backend + monkeypatch helper
# ---------------------------------------------------------------------------


class CaptureBackend:
    """In-process email backend that records every `send()` call."""

    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


@pytest.fixture
def capture_backend(monkeypatch):
    backend = CaptureBackend()
    monkeypatch.setattr(
        "src.app.core.subscriptions.notifications.get_email_backend",
        lambda: backend,
    )
    return backend


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_org_with_owner(
    *,
    owner_role_name: str = "owner",
    grant_billing_manage: bool = False,
    owner_email: str | None = None,
    owner_first_name: str = "Ada",
    org_name: str = "Test Co",
) -> tuple[uuid.UUID, str]:
    """Create an org with one active member tied to a named role."""
    from tests.conftest import TestSession

    email = owner_email or f"owner-{uuid.uuid4().hex[:6]}@demo.local"

    async with TestSession() as session:
        org = Organization(
            id=uuid.uuid4(),
            name=org_name,
            slug=f"em-{uuid.uuid4().hex[:6]}",
        )
        session.add(org)
        await session.flush()

        role = Role(
            id=uuid.uuid4(),
            org_id=org.id,
            name=owner_role_name,
            is_system=True,
        )
        session.add(role)
        await session.flush()

        if grant_billing_manage:
            perm_id = (
                await session.execute(
                    select(Permission.id).where(Permission.key == "billing.manage")
                )
            ).scalar_one_or_none()
            if perm_id is None:
                stmt = (
                    pg_insert(Permission)
                    .values(
                        key="billing.manage",
                        description="billing.manage",
                        module="subscriptions",
                    )
                    .on_conflict_do_nothing(index_elements=["key"])
                    .returning(Permission.id)
                )
                perm_id = (await session.execute(stmt)).scalar_one_or_none()
                if perm_id is None:
                    perm_id = (
                        await session.execute(
                            select(Permission.id).where(Permission.key == "billing.manage")
                        )
                    ).scalar_one()
            session.add(
                RolePermission(role_id=role.id, permission_id=perm_id),
            )
            await session.flush()

        login = UserLogin(
            user_id=f"t-{uuid.uuid4().hex[:8]}",
            password=hash_password("Pw@1234"),
            is_active=True,
        )
        session.add(login)
        await session.flush()

        session.add(
            LegacyUserInfo(
                member_id=login.id,
                first_name=owner_first_name,
                last_name="Lovelace",
                email=email,
                mobile_no="0",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org.id,
                user_member_id=login.id,
                role_id=role.id,
                status="active",
                is_active=True,
                is_demo=False,
            )
        )
        await session.commit()
        return org.id, email


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_key", list(RENDERERS.keys()))
def test_every_template_renders_under_minimal_context(template_key):
    result = render(template_key, {})
    assert result is not None
    subject, html, text = result
    assert isinstance(subject, str) and subject.strip()
    assert isinstance(html, str) and html.strip()
    assert isinstance(text, str) and text.strip()
    # All templates carry the product name. Asserts we didn't accidentally
    # ship "FurniCRM" in customer copy.
    assert "CRM" in subject + html + text
    assert "FurniCRM" not in subject + html + text


def test_unknown_template_key_returns_none():
    assert render("not_a_template", {}) is None


def test_owner_first_name_falls_back_when_missing():
    _, _, text = render("trial_expired", {})
    assert "Hi there," in text


def test_owner_first_name_used_when_provided():
    _, _, text = render("trial_expired", {"owner_first_name": "Ajay"})
    assert "Hi Ajay," in text


def test_payment_succeeded_includes_invoice_pdf():
    _, html, text = render(
        "payment_succeeded",
        {
            "amount_paid_usd": 60,
            "invoice_pdf_url": "https://invoice.example.com/x.pdf",
            "billing_url": "https://app.example.com/billing",
        },
    )
    assert "https://invoice.example.com/x.pdf" in html
    assert "https://invoice.example.com/x.pdf" in text


# ---------------------------------------------------------------------------
# send_billing_email — Owner resolution + dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_billing_email_dispatches_to_owner_email(
    layered_client,
    capture_backend,
):
    org_id, owner_email = await _seed_org_with_owner(
        owner_role_name="owner",
        owner_first_name="Ajay",
    )

    await send_billing_email(
        org_id=org_id,
        template_key="trial_expired",
        context={},
    )

    assert len(capture_backend.sent) == 1
    email = capture_backend.sent[0]
    assert email.to == owner_email
    assert "trial has ended" in email.subject.lower()
    assert "Hi Ajay," in (email.body_text or "")


@pytest.mark.asyncio
async def test_send_billing_email_falls_back_to_billing_manage(
    layered_client,
    capture_backend,
):
    """If no role named 'owner' exists, the resolver finds the member
    whose role has `billing.manage`."""
    org_id, owner_email = await _seed_org_with_owner(
        owner_role_name="admin",
        grant_billing_manage=True,
    )

    await send_billing_email(
        org_id=org_id,
        template_key="payment_succeeded",
        context={"amount_paid_usd": 60},
    )

    assert len(capture_backend.sent) == 1
    assert capture_backend.sent[0].to == owner_email


@pytest.mark.asyncio
async def test_send_billing_email_logs_and_skips_when_no_member(
    layered_client,
    capture_backend,
):
    from tests.conftest import TestSession

    async with TestSession() as session:
        org = Organization(
            id=uuid.uuid4(),
            name="Empty Co",
            slug=f"empty-{uuid.uuid4().hex[:6]}",
        )
        session.add(org)
        await session.commit()

    await send_billing_email(
        org_id=org.id,
        template_key="trial_expired",
        context={},
    )

    assert capture_backend.sent == []


@pytest.mark.asyncio
async def test_send_billing_email_swallows_backend_errors(
    layered_client,
    monkeypatch,
):
    """A misconfigured SMTP backend must not propagate — the parent
    flow (webhook handler, lifecycle task) keeps running."""
    org_id, _ = await _seed_org_with_owner()

    class ExplodingBackend:
        async def send(self, email):  # noqa: ARG002
            raise RuntimeError("smtp_down")

    monkeypatch.setattr(
        "src.app.core.subscriptions.notifications.get_email_backend",
        lambda: ExplodingBackend(),
    )

    # Must not raise.
    await send_billing_email(
        org_id=org_id,
        template_key="trial_expired",
        context={},
    )
