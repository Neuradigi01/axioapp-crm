"""Tests for `src.app.shared.context` and `TenantContextMiddleware`."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.app.shared.context import RequestContext, get_context, reset_context, set_context
from src.app.shared.middleware import TenantContextMiddleware


def test_get_context_default_is_empty():
    ctx = get_context()
    assert ctx.org_id is None
    assert ctx.user_id is None


def test_set_and_reset_context_roundtrip():
    new_id = uuid.uuid4()
    token = set_context(RequestContext(org_id=new_id))
    try:
        assert get_context().org_id == new_id
    finally:
        reset_context(token)
    assert get_context().org_id is None


def _build_probe_app() -> Starlette:
    """Tiny ASGI app that echoes the current context org_id + request_id."""

    async def _probe(request):
        ctx = get_context()
        return JSONResponse(
            {
                "org_id": str(ctx.org_id) if ctx.org_id else None,
                "request_id": ctx.request_id,
            }
        )

    app = Starlette(routes=[Route("/probe", _probe)])
    app.add_middleware(TenantContextMiddleware)
    return app


@pytest.mark.asyncio
async def test_middleware_populates_context_from_header():
    org_id = uuid.uuid4()
    app = _build_probe_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/probe", headers={"X-Org-Id": str(org_id)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] == str(org_id)
    assert body["request_id"] is not None
    # And the X-Request-Id is echoed back in the response.
    assert resp.headers.get("X-Request-Id") == body["request_id"]


@pytest.mark.asyncio
async def test_middleware_resets_context_between_requests():
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    app = _build_probe_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        a = await client.get("/probe", headers={"X-Org-Id": str(org_a)})
        b = await client.get("/probe", headers={"X-Org-Id": str(org_b)})
        c = await client.get("/probe")  # no header → no org
    assert a.json()["org_id"] == str(org_a)
    assert b.json()["org_id"] == str(org_b)
    assert c.json()["org_id"] is None
    # After all requests the outer (test) context is unaffected.
    assert get_context().org_id is None


@pytest.mark.asyncio
async def test_middleware_ignores_malformed_uuid_header():
    app = _build_probe_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/probe", headers={"X-Org-Id": "not-a-uuid"})
    assert resp.status_code == 200
    assert resp.json()["org_id"] is None


@pytest.mark.asyncio
async def test_middleware_reuses_client_request_id():
    app = _build_probe_app()
    rid = "client-supplied-request-id"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/probe", headers={"X-Request-Id": rid})
    assert resp.json()["request_id"] == rid
    assert resp.headers.get("X-Request-Id") == rid
