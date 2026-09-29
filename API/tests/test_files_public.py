"""`GET /files/{key}` serves only declared public raster images (r2-storage Step 5)."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from PIL import Image

import src.app.main  # noqa: F401  (import order: see test_public_file_patterns)
from src.app.core.catalog.module import MODULE as CATALOG
from src.app.core.files import router as files_router_module
from src.app.core.files import service as files_service
from src.app.core.module_registry import ModuleRegistry
from src.app.packs.furniture.modules.custom_orders import service as custom_orders_service
from src.app.packs.furniture.modules.field_ops import service as field_ops_service
from src.app.packs.furniture.modules.inventory import service as inventory_service
from src.app.packs.real_estate.modules.property.module import MODULE as PROPERTY
from src.app.shared.files.image import require_image_upload
from src.app.shared.rate_limit import InMemoryRateLimiter
from src.app.shared.storage.local import LocalStorage

_HTML = b"<html><script>alert(1)</script></html>"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch) -> LocalStorage:
    backend = LocalStorage(root=str(tmp_path))
    monkeypatch.setattr(files_service, "get_storage", lambda: backend)
    registry = ModuleRegistry()
    registry.register(CATALOG)
    registry.register(PROPERTY)
    monkeypatch.setattr(files_service, "registry", registry)
    monkeypatch.setattr(
        files_router_module, "_limiter", InMemoryRateLimiter(max_hits=50, window_seconds=60.0)
    )
    return backend


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(files_router_module.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_public_image_served_with_security_headers(storage, client) -> None:
    key = f"catalog/{uuid.uuid4()}/{uuid.uuid4()}.png"
    await storage.put(key, _png())

    resp = await client.get(f"/files/{key}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.content == _png()

    again = await client.get(f"/files/{key}", headers={"If-None-Match": resp.headers["etag"]})
    assert again.status_code == 304
    assert again.content == b""


async def test_private_keys_are_404_even_when_present(storage, client) -> None:
    org = uuid.uuid4()
    private_keys = [
        f"{org}/call_recordings/{uuid.uuid4()}.mp3",
        f"{org}/imports/{uuid.uuid4()}/source.csv",
        f"{org}/messages/{uuid.uuid4()}/invoice.png",
        f"{org}/ai_assistants/{uuid.uuid4()}.bin",
    ]
    for key in private_keys:
        await storage.put(key, b"secret")
        assert (await client.get(f"/files/{key}")).status_code == 404, key
        probe = await client.get(f"/files/{key}", headers={"If-None-Match": "*"})
        assert probe.status_code == 404, key


async def test_non_raster_under_public_prefix_is_404(storage, client) -> None:
    base = f"{uuid.uuid4()}/property/{uuid.uuid4()}"
    for name in ("x.svg", "x.html", "x.pdf"):
        await storage.put(f"{base}/{name}", _HTML)
        assert (await client.get(f"/files/{base}/{name}")).status_code == 404, name


async def test_missing_and_traversal_keys_are_404(storage, client) -> None:
    org = uuid.uuid4()
    assert (await client.get(f"/files/catalog/{org}/{uuid.uuid4()}.png")).status_code == 404
    for key in (
        f"catalog/{org}/..%2F..%2Fsecret.png",
        f"catalog/{org}/%2e%2e/x.png",
        f"{org}/property/{uuid.uuid4()}/..%5Cx.png",
    ):
        assert (await client.get(f"/files/{key}")).status_code == 404, key


async def test_rate_limited_per_ip(storage, client, monkeypatch) -> None:
    monkeypatch.setattr(
        files_router_module, "_limiter", InMemoryRateLimiter(max_hits=2, window_seconds=60.0)
    )
    key = f"catalog/{uuid.uuid4()}/{uuid.uuid4()}.png"
    codes = [(await client.get(f"/files/{key}")).status_code for _ in range(3)]
    assert codes == [404, 404, 429]


def test_require_image_upload_rejects_html() -> None:
    with pytest.raises(HTTPException) as exc:
        require_image_upload(_HTML)
    assert exc.value.status_code == 422
    assert require_image_upload(_png()) == ("image/png", "png")


async def test_furniture_uploads_reject_disguised_html() -> None:
    """Sniffing runs before any DB access, so no session is needed."""
    item = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await inventory_service.set_item_cover(None, item_id=item, org_id=item, file_bytes=_HTML)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await field_ops_service.add_photo(None, visit_id=item, data=_HTML)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await custom_orders_service.add_photo(None, order_id=item, data=_HTML)
    assert exc.value.status_code == 422
