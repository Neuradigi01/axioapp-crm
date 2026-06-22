"""Blob storage package.

`get_storage()` is the single entry point call sites use:

    from src.app.shared.storage import get_storage
    ref = get_storage().put("catalog/<org>/<id>.jpg", data, content_type="image/jpeg")
    item.image_url = ref.url

The concrete backend is local disk for this build (see `LocalStorage`).
"""
from __future__ import annotations

from functools import lru_cache

from src.app.shared.storage.base import StorageBackend, StoredFileRef
from src.app.shared.storage.local import LocalStorage


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    """Return the process-wide `StorageBackend` (local disk)."""
    return LocalStorage()


__all__ = ["StorageBackend", "StoredFileRef", "LocalStorage", "get_storage"]
