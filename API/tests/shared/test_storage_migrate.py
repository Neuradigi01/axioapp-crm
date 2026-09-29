"""`storage-migrate` disk <-> R2 copy (r2-storage Step 8), against a moto S3 stub."""

from __future__ import annotations

import os
import uuid

import boto3
import pytest
from moto import mock_aws

from src.app.shared.storage import migrate
from src.app.shared.storage.config import R2Settings
from src.app.shared.storage.local import LocalStorage
from src.app.shared.storage.r2 import R2Storage

_BUCKET = "crm-migrate-test"


@pytest.fixture
def r2():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        settings = R2Settings(
            account_id="acct", access_key_id="AKIA", secret_access_key="x", bucket=_BUCKET
        )
        yield R2Storage(settings, client=client), client


def _write(root, key: str, data: bytes) -> None:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_temp_and_hidden_keys_are_not_migratable() -> None:
    org = uuid.uuid4()
    assert migrate.is_migratable_key(f"{org}/property/{uuid.uuid4()}/a.jpg")
    assert migrate.is_migratable_key(f"catalog/{org}/a.jpg")
    assert not migrate.is_migratable_key("pending-inbound/abc/payload.json")
    assert not migrate.is_migratable_key("pending-events/abc/payload.json")
    assert not migrate.is_migratable_key(f"{org}/staging/{uuid.uuid4()}/a.pdf")
    assert not migrate.is_migratable_key(".storage-migrate.lock")
    assert not migrate.is_migratable_key("../etc/passwd")


async def test_forward_copies_with_content_type_and_is_idempotent(tmp_path, r2) -> None:
    storage, _ = r2
    org = uuid.uuid4()
    image = f"catalog/{org}/{uuid.uuid4()}.png"
    recording = f"{org}/call_recordings/{uuid.uuid4()}.mp3"
    _write(tmp_path, image, b"\x89PNG....")
    _write(tmp_path, recording, b"ID3....")
    _write(tmp_path, "pending-inbound/x/payload.json", b"{}")
    _write(tmp_path, f"{org}/staging/{uuid.uuid4()}/a.pdf", b"%PDF")
    os.symlink("/etc/hostname", tmp_path / str(org) / "leak.txt")

    dry = await migrate.migrate_to_r2(tmp_path, storage, dry_run=True, only_missing=False)
    assert (dry.copied, dry.failed) == (2, 0)
    assert await storage.raw_etag(image) is None

    first = await migrate.migrate_to_r2(tmp_path, storage, dry_run=False, only_missing=False)
    assert (first.copied, first.failed) == (2, 0)
    assert (await storage.stat(image)).content_type == "image/png"
    assert (await storage.stat(recording)).content_type == "audio/mpeg"
    assert await storage.raw_etag(f"{org}/leak.txt") is None
    assert await storage.raw_etag("pending-inbound/x/payload.json") is None

    again = await migrate.migrate_to_r2(tmp_path, storage, dry_run=False, only_missing=False)
    assert (again.copied, again.skipped) == (0, 2)


async def test_changed_file_recopied_but_only_missing_never_overwrites(tmp_path, r2) -> None:
    storage, _ = r2
    key = f"{uuid.uuid4()}/inventory/{uuid.uuid4()}/cover.jpg"
    _write(tmp_path, key, b"old-cover")
    await migrate.migrate_to_r2(tmp_path, storage, dry_run=False, only_missing=False)

    # After the flip a user uploads a new cover straight to R2 ...
    await storage.put(key, b"new-cover-from-r2")
    # ... and the post-flip catch-up pass must not clobber it.
    report = await migrate.migrate_to_r2(tmp_path, storage, dry_run=False, only_missing=True)
    assert report.copied == 0
    assert await storage.get(key) == b"new-cover-from-r2"

    # The pre-flip pass copies a disk file whose content changed.
    report = await migrate.migrate_to_r2(tmp_path, storage, dry_run=False, only_missing=False)
    assert report.copied == 1
    assert await storage.get(key) == b"old-cover"


async def test_reverse_restores_to_disk_and_drops_hostile_keys(tmp_path, r2) -> None:
    storage, client = r2
    org = uuid.uuid4()
    key = f"{org}/property/{uuid.uuid4()}/a.jpg"
    await storage.put(key, b"jpeg")
    client.put_object(Bucket=_BUCKET, Key="../../escape.txt", Body=b"evil")
    client.put_object(Bucket=_BUCKET, Key=f"{org}/../../escape2.txt", Body=b"evil")
    root = tmp_path / "storage"
    local = LocalStorage(root=str(root))

    report = await migrate.migrate_to_disk(storage, local, root, dry_run=False, only_missing=False)
    assert report.copied == 1
    assert (root / key).read_bytes() == b"jpeg"
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent / "escape.txt").exists()

    again = await migrate.migrate_to_disk(storage, local, root, dry_run=False, only_missing=True)
    assert again.copied == 0


def test_lock_refuses_second_run(tmp_path) -> None:
    lock = migrate._acquire_lock(tmp_path)
    try:
        with pytest.raises(migrate.MigrationLocked):
            migrate._acquire_lock(tmp_path)
    finally:
        lock.unlink()
    migrate._acquire_lock(tmp_path).unlink()
