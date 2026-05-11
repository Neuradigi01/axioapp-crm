import pytest
from fastapi import HTTPException
from src.core.security.access_guard import AccessGuard


@pytest.mark.asyncio
async def test_access_granted_with_matching_right():
    guard = AccessGuard([15])
    payload = {"user_id": "test", "role": "Admin", "access_rights": "15"}
    result = await guard(payload)
    assert result["user_id"] == "test"


@pytest.mark.asyncio
async def test_access_denied_without_right():
    guard = AccessGuard([15])
    payload = {"user_id": "test", "role": "Admin", "access_rights": "1,10"}
    with pytest.raises(HTTPException) as exc_info:
        await guard(payload)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_access_granted_with_partial_match():
    guard = AccessGuard([15, 20])
    payload = {"user_id": "test", "role": "Admin", "access_rights": "1,10,15"}
    result = await guard(payload)
    assert result["user_id"] == "test"


@pytest.mark.asyncio
async def test_access_denied_empty_rights():
    guard = AccessGuard([15])
    payload = {"user_id": "test", "role": "Admin", "access_rights": ""}
    with pytest.raises(HTTPException) as exc_info:
        await guard(payload)
    assert exc_info.value.status_code == 403
