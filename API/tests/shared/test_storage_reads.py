"""Import + call-recording reads go through `StorageBackend` (r2-storage Step 2)."""

from __future__ import annotations

import pathlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.core.calls import service as calls_service
from src.app.core.contacts.imports import service as contact_imports_service
from src.app.core.leads.imports import service as lead_imports_service
from src.app.core.leads.imports.parser import parse_rows
from src.app.shared.storage.local import LocalStorage

_SRC_APP = pathlib.Path(__file__).resolve().parents[2] / "src" / "app"


def test_no_direct_storage_disk_reads_in_core_or_packs() -> None:
    """Every blob read goes through `get_storage()`, never `./storage` on disk."""
    offenders = [
        str(path.relative_to(_SRC_APP))
        for root in ("core", "packs")
        for path in (_SRC_APP / root).rglob("*.py")
        if 'Path("./storage")' in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.fixture
def storage(tmp_path, monkeypatch) -> LocalStorage:
    backend = LocalStorage(root=str(tmp_path))
    monkeypatch.setattr("src.app.shared.storage.get_storage", lambda: backend)
    monkeypatch.setattr(lead_imports_service, "get_storage", lambda: backend)
    monkeypatch.setattr(contact_imports_service, "get_storage", lambda: backend)
    return backend


def test_parse_rows_reads_csv_bytes() -> None:
    header, rows = parse_rows("x/source.csv", b"Name,Phone\nAsha,98765\n", {"Name": "name"})
    assert header.columns == ["Name", "Phone"]
    assert [r.mapped for r in rows] == [{"name": "Asha"}]


async def test_lead_import_reports_read_through_storage(storage: LocalStorage) -> None:
    org = uuid.uuid4()
    key = f"{org}/imports/{uuid.uuid4()}/errors.csv"
    await storage.put(key, b"a,b\n")
    row = SimpleNamespace(org_id=org, error_report_path=key)

    assert await lead_imports_service.read_error_csv(row) == b"a,b\n"


async def test_lead_import_rejects_foreign_org_key(storage: LocalStorage) -> None:
    key = f"{uuid.uuid4()}/imports/{uuid.uuid4()}/errors.csv"
    await storage.put(key, b"secret")
    row = SimpleNamespace(org_id=uuid.uuid4(), error_report_path=key)

    with pytest.raises(HTTPException) as exc:
        await lead_imports_service.read_error_csv(row)
    assert exc.value.status_code == 404


async def test_contact_import_source_read_through_storage(storage: LocalStorage) -> None:
    org = uuid.uuid4()
    key = f"imports/{org}/{uuid.uuid4()}.csv"
    await storage.put(key, b"phone\n1\n")

    ok = SimpleNamespace(org_id=org, storage_path=key)
    assert await contact_imports_service._read_file_bytes(ok) == b"phone\n1\n"

    foreign = SimpleNamespace(org_id=uuid.uuid4(), storage_path=key)
    with pytest.raises(HTTPException) as exc:
        await contact_imports_service._read_file_bytes(foreign)
    assert exc.value.status_code == 404


def _patch_call(monkeypatch, call: SimpleNamespace) -> None:
    async def _get_call(_session, _call_id):
        return call

    monkeypatch.setattr(calls_service, "get_call", _get_call)


async def test_recording_streams_uploaded_bytes(storage: LocalStorage, monkeypatch) -> None:
    org = uuid.uuid4()
    key = f"{org}/call_recordings/{uuid.uuid4()}.mp3"
    await storage.put(key, b"ID3" + b"x" * 100_000)
    _patch_call(monkeypatch, SimpleNamespace(org_id=org, recording_file_path=key))

    chunks, content_type, size = await calls_service.read_recording_file(None, call_id=uuid.uuid4())
    body = b"".join([c async for c in chunks])
    assert content_type == "audio/mpeg"
    assert size == len(body) == 100_003


async def test_recording_foreign_org_key_is_404(storage: LocalStorage, monkeypatch) -> None:
    key = f"{uuid.uuid4()}/call_recordings/{uuid.uuid4()}.mp3"
    await storage.put(key, b"ID3")
    _patch_call(monkeypatch, SimpleNamespace(org_id=uuid.uuid4(), recording_file_path=key))

    with pytest.raises(HTTPException) as exc:
        await calls_service.read_recording_file(None, call_id=uuid.uuid4())
    assert exc.value.status_code == 404


async def test_recording_missing_blob_is_410(storage: LocalStorage, monkeypatch) -> None:
    org = uuid.uuid4()
    key = f"{org}/call_recordings/{uuid.uuid4()}.mp3"
    _patch_call(monkeypatch, SimpleNamespace(org_id=org, recording_file_path=key))

    with pytest.raises(HTTPException) as exc:
        await calls_service.read_recording_file(None, call_id=uuid.uuid4())
    assert exc.value.status_code == 410
