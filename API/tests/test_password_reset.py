"""Tests for `POST /api/v1/auth/forgot-password` and `/reset-password`."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.app.shared.security.password import verify_password
from src.models.password_reset import PasswordResetToken
from src.models.user import UserLogin


def _email_patch():
    return patch(
        "src.app.core.auth.password.service.email_provider.send_password_reset_email",
        new_callable=AsyncMock,
        return_value=None,
    )


async def _latest_token_for(db, member_id: int) -> PasswordResetToken | None:
    rows = (
        await db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.member_id == member_id)
            .order_by(PasswordResetToken.id.desc())
        )
    ).scalars().all()
    return rows[0] if rows else None


@pytest.mark.asyncio
async def test_forgot_password_issues_token_and_sends_email_for_known_email(
    layered_client, seeded_admin
):
    user = seeded_admin["user"]
    with _email_patch() as mock_send:
        resp = await layered_client.post(
            "/api/v1/auth/forgot-password",
            json={"identifier": user.email},
        )
    assert resp.status_code == 200, resp.text
    assert "message" in resp.json()
    mock_send.assert_awaited_once()
    args, _ = mock_send.call_args
    assert args[0] == user.email
    assert isinstance(args[1], str) and len(args[1]) > 30  # urlsafe(64) ~86 chars


@pytest.mark.asyncio
async def test_forgot_password_returns_200_for_unknown_identifier_without_sending(
    layered_client,
):
    with _email_patch() as mock_send:
        resp = await layered_client.post(
            "/api/v1/auth/forgot-password",
            json={"identifier": "nobody@example.com"},
        )
    assert resp.status_code == 200, resp.text
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_password_updates_password_and_invalidates_token(
    layered_client, seeded_admin, test_db
):
    user = seeded_admin["user"]
    with _email_patch():
        await layered_client.post(
            "/api/v1/auth/forgot-password", json={"identifier": user.email}
        )

    token_row = await _latest_token_for(test_db, user.id)
    assert token_row is not None and not token_row.is_used

    resp = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_row.token, "new_password": "NewSecret!42"},
    )
    assert resp.status_code == 200, resp.text

    await test_db.refresh(token_row)
    assert token_row.is_used is True

    refreshed_user = (
        await test_db.execute(select(UserLogin).where(UserLogin.id == user.id))
    ).scalar_one()
    assert verify_password("NewSecret!42", refreshed_user.password) is True
    assert verify_password("Admin@123", refreshed_user.password) is False


@pytest.mark.asyncio
async def test_reset_password_rejects_unknown_token(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "Whatever!42"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_reset_password_rejects_expired_token(
    layered_client, seeded_admin, test_db
):
    user = seeded_admin["user"]
    expired = PasswordResetToken(
        member_id=user.id,
        user_type="User",
        token="expired-token-xyz",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    test_db.add(expired)
    await test_db.commit()

    resp = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "expired-token-xyz", "new_password": "Whatever!42"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_reset_password_rejects_reused_token(
    layered_client, seeded_admin, test_db
):
    user = seeded_admin["user"]
    with _email_patch():
        await layered_client.post(
            "/api/v1/auth/forgot-password", json={"identifier": user.email}
        )
    token_row = await _latest_token_for(test_db, user.id)

    first = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_row.token, "new_password": "FirstPass!42"},
    )
    assert first.status_code == 200

    second = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_row.token, "new_password": "SecondPass!42"},
    )
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_invalidates_other_outstanding_tokens(
    layered_client, seeded_admin, test_db
):
    """Two forgot-password requests in a row issue two tokens. After the
    first one is used to reset, the second one must no longer work —
    otherwise an attacker who phished an older token gets a window after
    the user has rotated their password."""
    user = seeded_admin["user"]
    with _email_patch():
        await layered_client.post(
            "/api/v1/auth/forgot-password", json={"identifier": user.email}
        )
        first_token = await _latest_token_for(test_db, user.id)

        await layered_client.post(
            "/api/v1/auth/forgot-password", json={"identifier": user.email}
        )
        second_token = await _latest_token_for(test_db, user.id)

    assert first_token.id != second_token.id

    resp = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": second_token.token, "new_password": "RotatedPass!42"},
    )
    assert resp.status_code == 200

    stale = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": first_token.token, "new_password": "StaleAttempt!42"},
    )
    assert stale.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_rejects_short_password(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "any-token", "new_password": "short"},
    )
    assert resp.status_code == 422, resp.text
