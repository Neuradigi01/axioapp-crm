"""Storage abstraction.

`StorageBackend` is the seam every uploaded blob (catalog/inventory
images, custom-order photos, field-visit photos, import source files)
passes through. The build ships a single local-disk implementation
(`LocalStorage`); the interface exists so a future S3/object-store
backend can be dropped in without touching any call site.

Paths handed to a backend are storage-relative POSIX keys
(e.g. `catalog/{org_id}/{item_id}.jpg`) — never absolute filesystem
paths. The backend owns the mapping from key to physical location and to
public URL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredFileRef:
    """Handle to a blob that was just written.

    `path` is the storage-relative key it lives under; `url` is the
    public, server-relative URL a browser can GET it from. Call sites
    persist `url` (e.g. into `image_url` / `cover_url`).
    """

    path: str
    url: str


class StorageBackend(ABC):
    """Write blobs and resolve their public URLs."""

    @abstractmethod
    def put(self, path: str, data: bytes, content_type: str | None = None) -> StoredFileRef:
        """Persist `data` under storage-relative `path` and return a ref.

        `content_type` is advisory — local disk ignores it (the static
        mount infers MIME on serve); an object-store backend would record
        it as response metadata.
        """

    @abstractmethod
    def url(self, path: str) -> str:
        """Public, server-relative URL for the object at `path`."""
