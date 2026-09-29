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


async def test_mailgun_attachment_committed_then_streamed(tmp_path, monkeypatch) -> None:
    """Staged attachment → storage under {org}/messages/{id}/ → streamed back."""
    from src.app.core.conversations import service as conversations_service
    from src.app.core.email.mailgun import service as mailgun_service

    backend = LocalStorage(root=str(tmp_path / "blobs"))
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "disk"))
    monkeypatch.setattr(mailgun_service, "get_storage", lambda: backend)
    monkeypatch.setattr(conversations_service, "get_storage", lambda: backend)
    org, request_id, message_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    staging = tmp_path / "disk" / str(org) / "staging" / str(request_id)
    staging.mkdir(parents=True)
    (staging / "invoice.pdf").write_bytes(b"%PDF-1.4 body")

    await mailgun_service.commit_attachments(
        org_id=org, request_id=request_id, message_id=message_id
    )
    assert not staging.exists()

    message = SimpleNamespace(org_id=org, id=message_id)
    chunks, size = await conversations_service.open_message_attachment(message, "invoice.pdf")
    assert b"".join([c async for c in chunks]) == b"%PDF-1.4 body"
    assert size == 13

    with pytest.raises(HTTPException) as exc:
        await conversations_service.open_message_attachment(message, "missing.pdf")
    assert exc.value.status_code == 404


async def test_messages_orphan_sweep_removes_only_rowless_attachments(
    tmp_path, monkeypatch
) -> None:
    """The sweep lists `{org}/messages/` in storage and deletes folders
    whose Message row is gone (DB access stubbed out)."""
    import contextlib

    from src.app.core.email.mailgun import orphan_cleanup

    backend = LocalStorage(root=str(tmp_path))
    org, live, orphan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await backend.put(f"{org}/messages/{live}/a.pdf", b"keep")
    await backend.put(f"{org}/messages/{orphan}/b.pdf", b"drop")
    await backend.put(f"{org}/messages/{orphan}/c.pdf", b"drop")

    async def _org_ids(_session):
        return [org]

    async def _existing(_session, ids):
        return {i for i in ids if i == live}

    monkeypatch.setattr(orphan_cleanup, "get_storage", lambda: backend)
    monkeypatch.setattr(orphan_cleanup, "async_session", contextlib.nullcontext)
    monkeypatch.setattr(orphan_cleanup.mailgun_da, "list_org_ids", _org_ids)
    monkeypatch.setattr(orphan_cleanup.mailgun_da, "existing_message_ids", _existing)

    assert await orphan_cleanup._sweep_messages_orphans_async() == 1
    assert await backend.get(f"{org}/messages/{live}/a.pdf") == b"keep"
    assert [k async for k in backend.list_keys(f"{org}/messages/{orphan}")] == []


async def test_quarantine_payload_kept_in_storage_and_deleted(tmp_path, monkeypatch) -> None:
    """Quarantining copies the pending delivery into storage (it outlives
    the ingest task's local cleanup); discard/purge delete it again."""
    import shutil

    from src.app.core.email.quarantine import service as quarantine_service

    backend = LocalStorage(root=str(tmp_path / "blobs"))
    monkeypatch.setattr(quarantine_service, "get_storage", lambda: backend)
    monkeypatch.setattr(quarantine_service.data_access, "add_quarantine", lambda db, row: row)

    class _FakeDb:
        async def commit(self) -> None:
            return None

        async def refresh(self, _row) -> None:
            return None

    pending = tmp_path / "pending-inbound" / uuid.uuid4().hex
    pending.mkdir(parents=True)
    (pending / "payload.json").write_text('{"subject": "hi"}')
    (pending / "attachment_0_a.pdf").write_bytes(b"%PDF")
    org = uuid.uuid4()

    row = await quarantine_service.enqueue_quarantine(
        _FakeDb(),
        org_id=org,
        endpoint_id=None,
        mailgun_delivery_id="d1",
        from_address="Spam@Ex.com",
        from_display_name=None,
        to_recipient="in@crm.test",
        subject="hi",
        body_snippet="hi",
        attachment_summary=[],
        reason_code="blocked_sender",
        reason_detail={},
        pending_dir=pending,
    )
    assert row.payload_path == f"{org}/quarantine/{row.id}"

    shutil.rmtree(pending)  # the ingest task's cleanup
    assert await backend.get(f"{row.payload_path}/payload.json") == b'{"subject": "hi"}'
    assert await backend.get(f"{row.payload_path}/attachment_0_a.pdf") == b"%PDF"

    await quarantine_service._delete_payload(row.payload_path)
    assert [k async for k in backend.list_keys(row.payload_path)] == []

    # Legacy rows hold a local path that the ingest task already removed.
    await quarantine_service._delete_payload("storage/pending-inbound/abc")
