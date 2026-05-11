import traceback as tb
import orjson
from fastapi import Request as FastAPIRequest
from src.core.logger import logger
from src.core.db import async_session
from src.models.error_log import ErrorLog
from config import IS_DEVELOPMENT


async def log_error_to_db(
    exc: Exception,
    request: FastAPIRequest | None = None,
    user_id: str | None = None,
    user_role: str | None = None,
    status_code: int = 500,
):
    error_type = type(exc).__name__
    error_message = str(exc)
    traceback_str = tb.format_exc()

    route = None
    method = None
    request_body = None
    query_params = None
    ip_address = None
    user_agent = None

    if request:
        route = str(request.url)
        method = request.method
        ip_address = _get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")
        query_params = str(request.query_params) if request.query_params else None

        try:
            body = await request.body()
            if body:
                try:
                    parsed = orjson.loads(body)
                    _mask_sensitive_fields(parsed)
                    request_body = orjson.dumps(parsed).decode("utf-8")
                except Exception:
                    request_body = body.decode("utf-8", errors="replace")[:2000]
        except Exception:
            pass

    logger.error(
        f"{error_type}: {error_message} | "
        f"Route: {method} {route} | "
        f"User: {user_id} ({user_role}) | "
        f"IP: {ip_address}",
        exc_info=True,
    )

    try:
        error_log = ErrorLog(
            error_type=error_type,
            error_message=error_message[:2000],
            traceback=traceback_str[:5000] if traceback_str else None,
            route=route[:500] if route else None,
            method=method,
            request_body=request_body[:5000] if request_body else None,
            query_params=query_params[:2000] if query_params else None,
            user_id=user_id,
            user_role=user_role,
            ip_address=ip_address,
            user_agent=user_agent[:1000] if user_agent else None,
            status_code=status_code,
        )
        async with async_session() as db:
            db.add(error_log)
            await db.commit()
    except Exception as db_exc:
        logger.error(f"Failed to log error to database: {db_exc}")

    if IS_DEVELOPMENT:
        return error_message
    return "An unknown error occurred!"


def _get_client_ip(request: FastAPIRequest) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


SENSITIVE_FIELDS = {"password", "new_password", "old_password", "token", "secret", "otp_code", "two_factor_code"}


def _mask_sensitive_fields(data: dict):
    for key in data:
        if key.lower() in SENSITIVE_FIELDS:
            data[key] = "***"
        elif isinstance(data[key], dict):
            _mask_sensitive_fields(data[key])
