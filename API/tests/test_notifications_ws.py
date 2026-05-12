"""WebSocket coverage for /api/v1/notifications/stream.

Uses starlette's sync `TestClient.websocket_connect` (its in-memory
ASGI WebSocket transport — no real network or `wsproto` dep needed).
The async DB fixtures `layered_client` + `seeded_admin` are unused
here because TestClient is sync and we need to interact with the
WebSocket inside its `with` block.

Setup mirrors `seeded_admin` synchronously via the existing test
engine so we can log in through the HTTP layer and get a real JWT.

Coverage:
  - Bad token → server closes the handshake (TestClient raises).
  - Valid token → accept, manager registers the connection, `notify()`
    pushes a JSON-encoded NotificationOut to the socket, manager
    de-registers on disconnect.
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.app.core.notifications import notify
from src.app.core.notifications.manager import manager
from src.app.core.permissions.models import Role
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.security.password import hash_password


@pytest_asyncio.fixture
async def ws_user(layered_client):
    """Insert a fresh org+role+user via the test DB. Returns dict with creds."""
    from tests.conftest import TestSession

    org_id = uuid.uuid4()
    role_id = uuid.uuid4()
    user_id = uuid.uuid4()
    slug = f"ws-{org_id.hex[:6]}"
    email = f"ws-{user_id.hex[:6]}@demo.local"
    password = "Ws@12345"

    async with TestSession() as session:
        session.add(Organization(id=org_id, name="WS", slug=slug))
        await session.flush()
        session.add(Role(id=role_id, org_id=org_id, name="ws", is_system=True))
        await session.flush()
        session.add(
            User(
                id=user_id,
                org_id=org_id,
                email=email,
                password_hash=hash_password(password),
                full_name="WS Tester",
                role_id=role_id,
                is_active=True,
            )
        )
        await session.commit()

    # `layered_client` will be reused only to issue a login → token.
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": slug},
    )
    assert resp.status_code == 200, resp.text
    return {
        "org_id": org_id,
        "user_id": user_id,
        "token": resp.json()["access_token"],
    }


def test_ws_rejects_bad_token():
    """A malformed JWT closes the handshake with policy-violation."""
    from src.app.main import app

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/notifications/stream?token=not-a-jwt"
        ) as ws:
            ws.receive_text()


@pytest.mark.asyncio
async def test_ws_accepts_good_token_and_broadcasts(ws_user):
    """Open the socket, register, fire `notify`, expect the JSON push."""
    from src.app.main import app

    user_id: uuid.UUID = ws_user["user_id"]
    org_id: uuid.UUID = ws_user["org_id"]
    token: str = ws_user["token"]

    client = TestClient(app)
    received: list[str] = []
    connected = threading.Event()
    done = threading.Event()

    def consumer() -> None:
        try:
            with client.websocket_connect(
                f"/api/v1/notifications/stream?token={token}"
            ) as ws:
                connected.set()
                # Wait for at most one message.
                received.append(ws.receive_text())
        finally:
            done.set()

    t = threading.Thread(target=consumer, daemon=True)
    t.start()
    # Give the connection a chance to register on the manager.
    for _ in range(20):
        if connected.is_set() and manager.is_connected(user_id):
            break
        await asyncio.sleep(0.05)
    assert manager.is_connected(user_id), "WS never registered with manager"

    await notify(
        org_id=org_id,
        user_id=user_id,
        type="lead.assigned",
        title="WS push",
        body="hello from notify",
        payload={"k": "v"},
    )

    # Wait for the consumer to receive + tear down.
    for _ in range(40):
        if done.is_set():
            break
        await asyncio.sleep(0.05)

    assert received, "no message received over WS"
    body = json.loads(received[0])
    assert body["type"] == "lead.assigned"
    assert body["title"] == "WS push"
    assert body["body"] == "hello from notify"
    assert body["payload"] == {"k": "v"}
    assert body["user_id"] == str(user_id)

    # Wait for manager de-registration.
    for _ in range(20):
        if not manager.is_connected(user_id):
            break
        await asyncio.sleep(0.05)
    assert not manager.is_connected(user_id)
