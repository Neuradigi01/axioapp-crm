"""Tests for `POST /api/v1/auth/verify-contact/send-otp` and `/verify-email`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import orjson
import pytest
from sqlalchemy import select

from src.app.core.auth.verification import service as verification_service
from src.app.core.auth.verification.service import VerificationError
from src.models.user import UserInfo
from src.utilities.fernet_util import fernet

# ──────────────────────────────────────────────────────────────────────
# Pure unit tests for token shape / validation (no DB, no HTTP)
# ──────────────────────────────────────────────────────────────────────


def test_build_email_verification_token_roundtrips():
    token = verification_service.build_email_verification_token(
        email="user@x.com", user_id="USR12345678"
    )
    payload = orjson.loads(fernet.decrypt(token))
    assert payload["type"] == "email_verification"
    assert payload["value"] == "user@x.com"
    assert payload["user_id"] == "USR12345678"
    assert payload["expires_at"] > int(datetime.now(UTC).timestamp())


def test_validate_otp_token_accepts_matching_payload():
    token = verification_service._build_otp_token("email", "u@x.com", "123456")
    # No exception on match
    verification_service.validate_otp_token(
        otp_token=token,
        otp_code="123456",
        expected_type="email",
        expected_value="u@x.com",
    )


def test_validate_otp_token_rejects_wrong_code():
    token = verification_service._build_otp_token("email", "u@x.com", "123456")
    with pytest.raises(VerificationError, match="Invalid OTP code"):
        verification_service.validate_otp_token(
            otp_token=token,
            otp_code="000000",
            expected_type="email",
            expected_value="u@x.com",
        )


def test_validate_otp_token_rejects_value_mismatch():
    token = verification_service._build_otp_token("email", "u@x.com", "123456")
    with pytest.raises(VerificationError, match="does not match"):
        verification_service.validate_otp_token(
            otp_token=token,
            otp_code="123456",
            expected_type="email",
            expected_value="other@x.com",
        )


def test_validate_otp_token_rejects_type_mismatch():
    token = verification_service._build_otp_token("email", "u@x.com", "123456")
    with pytest.raises(VerificationError, match="Invalid verification token"):
        verification_service.validate_otp_token(
            otp_token=token,
            otp_code="123456",
            expected_type="sms",
            expected_value="u@x.com",
        )


def test_validate_otp_token_rejects_garbage():
    with pytest.raises(VerificationError, match="Invalid verification token"):
        verification_service.validate_otp_token(
            otp_token="not-a-fernet-token",
            otp_code="123456",
            expected_type="email",
            expected_value="u@x.com",
        )


def test_validate_otp_token_rejects_expired():
    # Hand-build an expired token
    expired_ts = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    payload = orjson.dumps(
        {"type": "email", "value": "u@x.com", "otp": "123456", "expires_at": expired_ts}
    ).decode()
    token = fernet.encrypt(payload)
    with pytest.raises(VerificationError, match="expired"):
        verification_service.validate_otp_token(
            otp_token=token,
            otp_code="123456",
            expected_type="email",
            expected_value="u@x.com",
        )


# ──────────────────────────────────────────────────────────────────────
# Integration tests for the HTTP endpoints (need DB via layered_client)
# ──────────────────────────────────────────────────────────────────────


def _email_send_patch():
    return patch(
        "src.app.core.auth.verification.service.email_provider.send_otp_email",
        new_callable=AsyncMock,
        return_value=None,
    )


def _sms_send_patch():
    return patch(
        "src.app.core.auth.verification.service.sms_provider.send_otp_sms",
        new_callable=AsyncMock,
        return_value=None,
    )


@pytest.mark.asyncio
async def test_send_otp_email_returns_token(layered_client):
    with _email_send_patch() as mock_send:
        resp = await layered_client.post(
            "/api/v1/auth/verify-contact/send-otp",
            json={"type": "email", "value": "newuser@example.com"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["otp_token"]
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_otp_sms_returns_token(layered_client):
    with _sms_send_patch() as mock_send:
        resp = await layered_client.post(
            "/api/v1/auth/verify-contact/send-otp",
            json={"type": "sms", "value": "+919999999999"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["otp_token"]
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_otp_rejects_invalid_type(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/verify-contact/send-otp",
        json={"type": "telegram", "value": "@somebody"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_verify_email_marks_user_verified(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    # `seeded_admin` builds the user with the legacy `user_id` text login
    # handle on `tbl_user_login.user_id`.
    from src.models.user import UserLogin

    login_handle = (
        await test_db.execute(select(UserLogin.user_id).where(UserLogin.id == user.id))
    ).scalar_one()

    token = verification_service.build_email_verification_token(
        email=user.email, user_id=login_handle
    )

    resp = await layered_client.post(
        "/api/v1/auth/verify-contact/verify-email",
        json={"token": token},
    )
    assert resp.status_code == 200, resp.text

    refreshed = (
        await test_db.execute(
            select(UserInfo.is_email_verified).where(UserInfo.member_id == user.id)
        )
    ).scalar_one()
    assert refreshed is True


@pytest.mark.asyncio
async def test_verify_email_rejects_unknown_user(layered_client):
    token = verification_service.build_email_verification_token(
        email="ghost@x.com", user_id="USR00000000"
    )
    resp = await layered_client.post(
        "/api/v1/auth/verify-contact/verify-email",
        json={"token": token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_verify_email_rejects_email_mismatch(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    from src.models.user import UserLogin

    login_handle = (
        await test_db.execute(select(UserLogin.user_id).where(UserLogin.id == user.id))
    ).scalar_one()
    # Token claims a different email than the user currently has on file
    token = verification_service.build_email_verification_token(
        email="impostor@x.com", user_id=login_handle
    )
    resp = await layered_client.post(
        "/api/v1/auth/verify-contact/verify-email",
        json={"token": token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_verify_email_rejects_garbage_token(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/verify-contact/verify-email",
        json={"token": "not-a-real-fernet-token"},
    )
    assert resp.status_code == 400
