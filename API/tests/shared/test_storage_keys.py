"""Storage key guard + async `LocalStorage` round trip (r2-storage Step 1)."""

from __future__ import annotations

import uuid

import pytest

from src.app.shared.storage.keys import (
    assert_org_key,
    content_type_for,
    validate_key,
    validate_prefix,
)
from src.app.shared.storage.local import LocalStorage


@pytest.mark.parametrize(
    "key",
    ["", "../x", "/x", "a//b", "a\\b", "a/./b", "a/../b", "a\x00b", "a\nb", "a/"],
)
def test_validate_key_rejects_unsafe(key: str) -> None:
    with pytest.raises(ValueError):
        validate_key(key)


def test_validate_key_accepts_normal_key() -> None:
    key = f"{uuid.uuid4()}/property/{uuid.uuid4()}/{uuid.uuid4()}.jpg"
    assert validate_key(key) == key


@pytest.mark.parametrize("prefix", ["", "/", "not-a-uuid/x", "catalog", "catalog/abc", "../x"])
def test_validate_prefix_rejects_unscoped(prefix: str) -> None:
    with pytest.raises(ValueError):
        validate_prefix(prefix)


def test_validate_prefix_appends_slash() -> None:
    org = str(uuid.uuid4())
    assert validate_prefix(f"{org}/imports") == f"{org}/imports/"
    assert validate_prefix(f"catalog/{org}") == f"catalog/{org}/"
    assert validate_prefix(f"imports/{org}/") == f"imports/{org}/"


def test_assert_org_key_rejects_foreign_org() -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    assert assert_org_key(mine, f"{mine}/call_recordings/x.mp3")
    assert assert_org_key(mine, f"catalog/{mine}/x.jpg")
    assert assert_org_key(mine, f"imports/{mine}/x.csv")
    with pytest.raises(FileNotFoundError):
        assert_org_key(mine, f"{theirs}/call_recordings/x.mp3")
    with pytest.raises(FileNotFoundError):
        assert_org_key(mine, f"catalog/{theirs}/x.jpg")


def test_content_type_for() -> None:
    assert content_type_for("a/b.png") == "image/png"
    assert content_type_for("a/b.unknownext") == "application/octet-stream"


async def test_local_storage_round_trip(tmp_path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    org = uuid.uuid4()
    key = f"{org}/imports/{uuid.uuid4()}/source.png"

    ref = await storage.put(key, b"hello world", content_type="image/png")
    assert ref.path == key
    assert ref.url == f"/files/{key}"

    assert await storage.get(key) == b"hello world"
    chunks = [c async for c in storage.open_stream(key, chunk_size=4)]
    assert b"".join(chunks) == b"hello world"
    assert len(chunks) == 3

    first = await storage.stat(key)
    assert first.size == 11
    assert first.content_type == "image/png"
    assert (await storage.stat(key)).etag == first.etag

    assert await storage.delete(key) is True
    assert await storage.delete(key) is False
    with pytest.raises(FileNotFoundError):
        await storage.get(key)
    with pytest.raises(FileNotFoundError):
        await storage.stat(key)


async def test_list_keys_does_not_overmatch_sibling_prefix(tmp_path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    org = uuid.uuid4()
    await storage.put(f"{org}/imports/a.csv", b"1")
    await storage.put(f"{org}/imports/sub/b.csv", b"2")
    await storage.put(f"{org}/imports_old/c.csv", b"3")

    keys = [k async for k in storage.list_keys(f"{org}/imports")]
    assert keys == [f"{org}/imports/a.csv", f"{org}/imports/sub/b.csv"]


async def test_delete_directory_scoped_and_guarded(tmp_path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    org = uuid.uuid4()
    await storage.put(f"{org}/ai_assistants/a.bin", b"1")
    await storage.put(f"{org}/ai_assistants/x/profile/b.png", b"2")
    await storage.put(f"{org}/ai_assistants_old/c.bin", b"3")

    assert await storage.delete_directory(f"{org}/ai_assistants") == 2
    assert await storage.get(f"{org}/ai_assistants_old/c.bin") == b"3"
    assert await storage.delete_directory(f"{org}/ai_assistants") == 0

    with pytest.raises(ValueError):
        await storage.delete_directory("")
    with pytest.raises(ValueError):
        await storage.delete_directory("not-a-uuid/x")
