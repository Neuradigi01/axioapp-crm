"""Tests for 2FA enforcement at `POST /api/v1/auth/login` plus
`POST /api/v1/auth/2fa/try-another-way`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pyotp
import pytest
from sqlalchemy import select, update

from src.models.otp import OtpRequest
from src.models.user import UserLogin


def _otp_email_patch():
    return patch(
        "src.providers.otp_provider.email_provider.send_otp_email",
        new_callable=AsyncMock,
        return_value=None,
    )


def _otp_sms_patch():
    return patch(
        "src.providers.otp_provider.sms_provider.send_otp_sms",
        new_callable=AsyncMock,
        return_value=None,
    )


async def _enable_2fa(test_db, member_id: int, method: str, secret: str | None = None):
    await test_db.execute(
        update(UserLogin)
        .where(UserLogin.id == member_id)
        .values(
            two_factor_enabled=True,
            two_factor_method=method,
            two_factor_secret=secret,
        )
    )
    await test_db.commit()


async def _latest_otp_code(test_db, member_id: int) -> str | None:
    rows = (
        (
            await test_db.execute(
                select(OtpRequest)
                .where(OtpRequest.member_id == member_id)
                .order_by(OtpRequest.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return rows[0].otp_code if rows else None


@pytest.mark.asyncio
async def test_login_without_2fa_returns_access_token(layered_client, seeded_admin):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Admin@123", "org_slug": org.slug},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token")


@pytest.mark.asyncio
async def test_login_with_2fa_enabled_no_code_returns_challenge(
    layered_client, seeded_admin, test_db
):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    await _enable_2fa(test_db, user.id, method="email")

    with _otp_email_patch() as mock_send:
        resp = await layered_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "Admin@123", "org_slug": org.slug},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("requires_two_factor") is True
    assert body.get("method") == "email"
    assert "email" in body.get("available_methods", [])
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_with_2fa_email_valid_code_succeeds(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    await _enable_2fa(test_db, user.id, method="email")

    with _otp_email_patch():
        await layered_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "Admin@123", "org_slug": org.slug},
        )
        code = await _latest_otp_code(test_db, user.id)
    assert code

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "Admin@123",
            "org_slug": org.slug,
            "two_factor_code": code,
            "two_factor_method": "email",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token")


@pytest.mark.asyncio
async def test_login_with_2fa_invalid_code_is_401(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    await _enable_2fa(test_db, user.id, method="email")

    with _otp_email_patch():
        await layered_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "Admin@123", "org_slug": org.slug},
        )

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "Admin@123",
            "org_slug": org.slug,
            "two_factor_code": "000000",
        },
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_with_2fa_authenticator_totp_succeeds(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    secret = pyotp.random_base32()
    await _enable_2fa(test_db, user.id, method="authenticator", secret=secret)

    valid_code = pyotp.TOTP(secret).now()
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "Admin@123",
            "org_slug": org.slug,
            "two_factor_code": valid_code,
            "two_factor_method": "authenticator",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token")


@pytest.mark.asyncio
async def test_login_with_2fa_authenticator_wrong_code_is_401(
    layered_client, seeded_admin, test_db
):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    secret = pyotp.random_base32()
    await _enable_2fa(test_db, user.id, method="authenticator", secret=secret)

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "Admin@123",
            "org_slug": org.slug,
            "two_factor_code": "111111",
            "two_factor_method": "authenticator",
        },
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_try_another_way_dispatches_via_new_method(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    secret = pyotp.random_base32()
    # Preferred = authenticator, user wants email instead this round.
    await _enable_2fa(test_db, user.id, method="authenticator", secret=secret)

    with _otp_email_patch() as mock_send:
        resp = await layered_client.post(
            "/api/v1/auth/2fa/try-another-way",
            json={
                "email": user.email,
                "password": "Admin@123",
                "org_slug": org.slug,
                "method": "email",
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"] == "email"
    assert "email" in body["available_methods"]
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_another_way_rejects_wrong_password(layered_client, seeded_admin, test_db):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    await _enable_2fa(test_db, user.id, method="email")

    resp = await layered_client.post(
        "/api/v1/auth/2fa/try-another-way",
        json={
            "email": user.email,
            "password": "wrong-password",
            "org_slug": org.slug,
            "method": "email",
        },
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_try_another_way_rejects_when_2fa_disabled(layered_client, seeded_admin):
    user = seeded_admin["user"]
    org = seeded_admin["org"]
    resp = await layered_client.post(
        "/api/v1/auth/2fa/try-another-way",
        json={
            "email": user.email,
            "password": "Admin@123",
            "org_slug": org.slug,
            "method": "email",
        },
    )
    assert resp.status_code == 400, resp.text
