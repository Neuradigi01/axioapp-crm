"""Blob storage package.

`get_storage()` is the single entry point call sites use:

    from src.app.shared.storage import get_storage
    ref = await get_storage().put("catalog/<org>/<id>.jpg", data, content_type="image/jpeg")
    item.image_url = ref.url

The backend is chosen by ``STORAGE_BACKEND``: ``local`` (disk under
``STORAGE_ROOT``) or ``r2`` (Cloudflare R2). See `config.py`.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from src.app.shared.storage.base import StorageBackend, StoredFileRef, StoredFileStat
from src.app.shared.storage.config import (
    StorageConfigError,
    r2_settings,
    storage_backend_name,
    storage_root,
)
from src.app.shared.storage.keys import assert_org_key
from src.app.shared.storage.local import LocalStorage

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    """Return the process-wide `StorageBackend` for ``STORAGE_BACKEND``.
    Raises `StorageConfigError` when the configuration is incomplete."""
    if storage_backend_name() == "r2":
        from src.app.shared.storage.r2 import R2Storage

        return R2Storage(r2_settings())
    return LocalStorage(root=str(storage_root()))


async def probe_storage() -> None:
    """Log whether the configured backend is reachable. Never raises:
    an R2 outage at boot must not take the whole API down — requests
    that need storage fail individually instead."""
    name = storage_backend_name()
    try:
        await get_storage().check_reachable()
    except Exception:
        logger.exception("storage: backend=%s is NOT reachable at startup", name)
    else:
        logger.info("storage: backend=%s reachable", name)


__all__ = [
    "LocalStorage",
    "StorageBackend",
    "StorageConfigError",
    "StoredFileRef",
    "StoredFileStat",
    "assert_org_key",
    "get_storage",
    "probe_storage",
    "storage_root",
]
