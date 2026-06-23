"""WebSocket endpoint for real-time notifications.

  WS /api/v1/notifications/stream?token=<jwt>

Browsers can't attach an `Authorization` header to a WebSocket
handshake, so the JWT comes in as a query parameter. We decode it,
verify the matching `auth_sessions` row is still alive (not revoked,
not expired), then register the socket with the in-process
`ConnectionManager`. When the client closes (or any error), the
socket is removed from the registry.

The endpoint deliberately doesn't read incoming frames from the
client — this is a server-push channel only. Any client send is
silently ignored (we just await `receive_text()` to keep the
connection open until the client closes).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from src.app.core import data_access
from src.app.core.auth.tokens import InvalidToken, decode_token
from src.app.core.notifications.manager import manager
from src.app.shared.db import async_session


ws_router = APIRouter()


@ws_router.websocket("/notifications/stream")
async def notifications_stream(
    websocket: WebSocket,
    token: str = Query(...),
) -> None:
    # 1) Decode the JWT before accept() so a bad token gets 1008 cleanly.
    try:
        claims = decode_token(token)
    except InvalidToken:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2) Verify the session row exists and is still live.
    async with async_session() as session:
        row = await data_access.get_auth_session(
            session, session_id=claims.token_id
        )
    if (
        row is None
        or row.revoked_at is not None
        or row.expires_at <= datetime.now(timezone.utc)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 3) Accept + register.
    await websocket.accept()
    await manager.connect(claims.user_id, websocket)

    try:
        # Server-push only. Loop on receive_text so the connection
        # stays open; any incoming frames are ignored.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(claims.user_id, websocket)
