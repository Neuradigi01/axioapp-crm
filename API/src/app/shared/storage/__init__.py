"""Blob storage package.

`get_storage()` is the single entry point call sites use:

    from src.app.shared.storage import get_storage
    ref = await get_storage().put("catalog/<org>/<id>.jpg", data, content_type="image/jpeg")
    item.image_url = ref.url

The concrete backend is local disk (see `LocalStorage`).
"""

from __future__ import annotations

from functools import lru_cache

from src.app.shared.storage.base import StorageBackend, StoredFileRef, StoredFileStat
from src.app.shared.storage.keys import assert_org_key
from src.app.shared.storage.local import LocalStorage


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    """Return the process-wide `StorageBackend` (local disk)."""
    return LocalStorage()


__all__ = [
    "StorageBackend",
    "StoredFileRef",
    "StoredFileStat",
    "LocalStorage",
    "assert_org_key",
    "get_storage",
]
