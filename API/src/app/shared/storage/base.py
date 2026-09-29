"""Storage abstraction.

`StorageBackend` is the seam every stored blob (catalog/inventory
images, custom-order and field-visit photos, property images, call
recordings, import sources and reports, AI-assistant files) passes
through. Call sites never touch the filesystem or an object store
directly, so the concrete backend can change without touching them.

Keys handed to a backend are storage-relative POSIX keys
(e.g. `catalog/{org_id}/{item_id}.jpg`) — never absolute filesystem
paths — and are checked by `keys.validate_key` / `keys.validate_prefix`.
The backend owns the mapping from key to physical location and to
public URL.

Every method except `url` is async: an object-store round trip must
never block the event loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

#: Default chunk size for `open_stream`.
DEFAULT_CHUNK_SIZE = 64 * 1024

#: Upper bound on how many objects one `delete_directory` call may
#: remove. A prefix that matches more is refused rather than deleted.
MAX_DIRECTORY_OBJECTS = 10_000


@dataclass(frozen=True, slots=True)
class StoredFileRef:
    """Handle to a blob that was just written.

    `path` is the storage-relative key it lives under; `url` is the
    public, server-relative URL a browser can GET it from. Call sites
    persist `url` (e.g. into `image_url` / `cover_url`).
    """

    path: str
    url: str


@dataclass(frozen=True, slots=True)
class StoredFileStat:
    """Metadata for a stored blob. `etag` is opaque to callers."""

    size: int
    etag: str
    content_type: str


class StorageBackend(ABC):
    """Read, write and delete blobs by storage-relative key."""

    @abstractmethod
    async def put(self, path: str, data: bytes, content_type: str | None = None) -> StoredFileRef:
        """Persist `data` under `path` and return a ref.

        `content_type` is recorded where the backend supports object
        metadata; otherwise it is derived from the key's extension.
        """

    @abstractmethod
    async def get(self, path: str) -> bytes:
        """Read + return the raw bytes at `path`. Raises
        `FileNotFoundError` on miss."""

    @abstractmethod
    def open_stream(self, path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        """Yield the blob at `path` in chunks without loading it whole.
        Raises `FileNotFoundError` on miss (on first iteration)."""

    @abstractmethod
    async def stat(self, path: str) -> StoredFileStat:
        """Size, opaque ETag and content type of the blob at `path`.
        Raises `FileNotFoundError` on miss."""

    @abstractmethod
    def url(self, path: str) -> str:
        """Public, server-relative URL for the object at `path`."""

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete the blob at `path`. Returns True if a blob was
        removed, False if there was nothing there."""

    @abstractmethod
    async def delete_directory(self, prefix: str) -> int:
        """Delete every blob under the org-scoped `prefix` and return
        the number removed. Raises `ValueError` when more than
        `MAX_DIRECTORY_OBJECTS` match."""

    @abstractmethod
    def list_keys(self, prefix: str) -> AsyncIterator[str]:
        """Yield every key under the org-scoped `prefix`."""
