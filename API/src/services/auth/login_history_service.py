from sqlalchemy.ext.asyncio import AsyncSession
from src.data_access import login_history_da
from src.data_access.resolution_da import resolve_member_id
from src.constants import messages


async def get_login_history(
    db: AsyncSession,
    user_id: str | None,
    match_exact: bool,
    page_index: int,
    page_size: int,
    current_token_id: int,
) -> dict:
    records, total = await login_history_da.get_login_history(
        db,
        user_id=user_id,
        match_exact=match_exact,
        page_index=page_index,
        page_size=page_size,
    )

    data = []
    for r in records:
        ip_details = r.ip_info or []
        first_ip = ip_details[0] if isinstance(ip_details, list) and ip_details else (ip_details if isinstance(ip_details, dict) else {})

        login_status = _resolve_login_status(r, current_token_id)

        device = r.device_info or {}
        loc = first_ip.get("loc", "")
        latitude, longitude = "", ""
        if loc and "," in loc:
            parts = loc.split(",")
            latitude, longitude = parts[0], parts[1]

        data.append({
            "token_id": r.id,
            "user_id": r.user_id,
            "user_type": r.user_type,
            "on_date": r.login_at.isoformat() if r.login_at else None,
            "ip_address": r.ip_address,
            "sender_ip": r.sender_ip,
            "city": first_ip.get("city", ""),
            "region": first_ip.get("region", ""),
            "country": first_ip.get("country", ""),
            "latitude": latitude,
            "longitude": longitude,
            "device": device.get("device", ""),
            "device_type": device.get("device_type", ""),
            "os": device.get("os", ""),
            "os_version": device.get("os_version", ""),
            "browser": device.get("browser", ""),
            "browser_version": device.get("browser_version", ""),
            "login_status": login_status,
            "logout_timestamp": r.logout_timestamp.isoformat() if r.logout_timestamp else None,
            "by_admin_token_id": r.by_admin_token_id,
        })

    return {"success": True, "data": data, "data_count": total}


async def logout_session(
    db: AsyncSession,
    token_id: int,
    current_user_id: str,
    current_user_type: str,
) -> dict:
    if current_user_type != "Admin":
        record = await login_history_da.get_by_id(db, token_id)
        if not record or record.user_id.lower() != current_user_id.lower():
            return {"success": False, "message": messages.INSUFFICIENT_PERMISSIONS}

    member_id = await resolve_member_id(db, current_user_id, current_user_type)
    if not member_id:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    success = await login_history_da.invalidate_token(
        db,
        token_id=token_id,
        logout_by_id=member_id,
        logout_by_type=current_user_type,
    )
    await db.commit()

    if success:
        return {"success": True, "message": messages.SESSION_LOGGED_OUT}
    return {"success": False, "message": messages.SESSION_ALREADY_INACTIVE}


async def logout_current(
    db: AsyncSession,
    token_id: int,
    user_id: str,
    user_type: str,
) -> dict:
    if not token_id:
        return {"success": False, "message": messages.INVALID_TOKEN}

    member_id = await resolve_member_id(db, user_id, user_type)
    if not member_id:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    await login_history_da.invalidate_token(
        db,
        token_id=token_id,
        logout_by_id=member_id,
        logout_by_type=user_type,
    )
    await db.commit()
    return {"success": True, "message": messages.LOGGED_OUT}


def _resolve_login_status(record, current_token_id: int) -> str:
    if record.id == current_token_id and record.is_token_active:
        return "Current Session"
    if record.is_login_successful and record.is_token_active:
        return "Active"
    if record.is_login_successful and not record.is_token_active:
        return record.logout_remarks or "Logged out"
    if record.is_valid_credentials:
        return "2FA-Pending"
    return "Failed"
