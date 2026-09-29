"""`R2Storage` against an in-memory S3 stub + backend selection (r2-storage Step 3)."""

from __future__ import annotations

import uuid

import boto3
import pytest
from moto import mock_aws

from src.app.shared import storage as storage_pkg
from src.app.shared.storage import r2 as r2_module
from src.app.shared.storage.config import R2Settings, StorageConfigError, r2_settings
from src.app.shared.storage.local import LocalStorage
from src.app.shared.storage.r2 import R2Storage

_BUCKET = "crm-test"
_SETTINGS = R2Settings(
    account_id="acct", access_key_id="AKIA", secret_access_key="super-secret", bucket=_BUCKET
)


@pytest.fixture
def r2():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        yield R2Storage(_SETTINGS, client=client), client


async def test_round_trip(r2) -> None:
    storage, _ = r2
    key = f"{uuid.uuid4()}/call_recordings/{uuid.uuid4()}.mp3"

    ref = await storage.put(key, b"ID3" + b"x" * 200_000)
    assert ref.path == key
    assert ref.url == f"/files/{key}"

    assert (await storage.get(key))[:3] == b"ID3"
    streamed = b"".join([c async for c in storage.open_stream(key, chunk_size=64 * 1024)])
    assert len(streamed) == 200_003

    stat = await storage.stat(key)
    assert stat.size == 200_003
    assert stat.content_type == "audio/mpeg"
    assert '"' not in stat.etag

    assert await storage.delete(key) is True
    assert await storage.delete(key) is False
    with pytest.raises(FileNotFoundError):
        await storage.get(key)
    with pytest.raises(FileNotFoundError):
        await storage.stat(key)
    with pytest.raises(FileNotFoundError):
        [c async for c in storage.open_stream(key)]


async def test_explicit_content_type_is_kept(r2) -> None:
    storage, _ = r2
    key = f"catalog/{uuid.uuid4()}/{uuid.uuid4()}.bin"
    await storage.put(key, b"\x89PNG", content_type="image/png")
    assert (await storage.stat(key)).content_type == "image/png"


async def test_unsafe_keys_rejected_before_any_call(r2) -> None:
    storage, _ = r2
    for key in ("../etc/passwd", "/abs", "a//b", "a\\b"):
        with pytest.raises(ValueError):
            await storage.put(key, b"x")
    with pytest.raises(ValueError):
        await storage.delete_directory("")


async def test_delete_directory_batches_and_stays_in_prefix(r2) -> None:
    storage, client = r2
    org = uuid.uuid4()
    for i in range(1500):
        client.put_object(Bucket=_BUCKET, Key=f"{org}/ai_assistants/{i}.bin", Body=b"x")
    client.put_object(Bucket=_BUCKET, Key=f"{org}/ai_assistants_old/keep.bin", Body=b"x")

    assert await storage.delete_directory(f"{org}/ai_assistants") == 1500
    remaining = [k async for k in storage.list_keys(str(org))]
    assert remaining == [f"{org}/ai_assistants_old/keep.bin"]


async def test_delete_directory_refuses_over_cap(r2, monkeypatch) -> None:
    storage, client = r2
    monkeypatch.setattr(r2_module, "MAX_DIRECTORY_OBJECTS", 3)
    org = uuid.uuid4()
    for i in range(4):
        client.put_object(Bucket=_BUCKET, Key=f"{org}/x/{i}", Body=b"x")

    with pytest.raises(ValueError):
        await storage.delete_directory(f"{org}/x")
    assert len([k async for k in storage.list_keys(f"{org}/x")]) == 4


async def test_list_keys_skips_unsafe_bucket_keys(r2) -> None:
    storage, client = r2
    org = uuid.uuid4()
    client.put_object(Bucket=_BUCKET, Key=f"{org}/a/ok.csv", Body=b"x")
    client.put_object(Bucket=_BUCKET, Key=f"{org}/a/../../escape", Body=b"x")

    assert [k async for k in storage.list_keys(f"{org}/a")] == [f"{org}/a/ok.csv"]


async def test_check_reachable(r2) -> None:
    storage, _ = r2
    await storage.check_reachable()


def test_missing_r2_vars_named_without_values(monkeypatch) -> None:
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "super-secret")
    monkeypatch.delenv("R2_BUCKET", raising=False)

    with pytest.raises(StorageConfigError) as exc:
        r2_settings()
    assert "R2_BUCKET" in str(exc.value)
    assert "super-secret" not in str(exc.value)
    assert "super-secret" not in repr(_SETTINGS)


def test_get_storage_selects_backend(monkeypatch) -> None:
    storage_pkg.get_storage.cache_clear()
    try:
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        assert isinstance(storage_pkg.get_storage(), LocalStorage)

        storage_pkg.get_storage.cache_clear()
        monkeypatch.setenv("STORAGE_BACKEND", "r2")
        for var, value in (
            ("R2_ACCOUNT_ID", "acct"),
            ("R2_ACCESS_KEY_ID", "AKIA"),
            ("R2_SECRET_ACCESS_KEY", "secret"),
            ("R2_BUCKET", _BUCKET),
        ):
            monkeypatch.setenv(var, value)
        backend = storage_pkg.get_storage()
        assert isinstance(backend, R2Storage)
        assert backend.bucket == _BUCKET

        storage_pkg.get_storage.cache_clear()
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        with pytest.raises(StorageConfigError):
            storage_pkg.get_storage()
    finally:
        storage_pkg.get_storage.cache_clear()


async def test_probe_storage_never_raises(monkeypatch) -> None:
    class _Down:
        async def check_reachable(self) -> None:
            raise ConnectionError("r2 down")

    monkeypatch.setattr(storage_pkg, "get_storage", lambda: _Down())
    await storage_pkg.probe_storage()
