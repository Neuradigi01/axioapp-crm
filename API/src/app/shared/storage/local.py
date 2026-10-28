"""Local-filesystem `StorageBackend`.

Blobs are written under `./storage/<key>` (resolved against the process
CWD) and served read-only by the `/files` static mount declared in
`main.py`. The `./storage` root is the same one the import readers join
their relative paths onto, so writes here are visible to those readers.
"""

from __future__ import annotations

from pathlib import Path

from src.app.shared.storage.base import StorageBackend, StoredFileRef


class LocalStorage(StorageBackend):
    """Disk-backed storage rooted at `root` (default `./storage`)."""

    #: Mount point the `/files` StaticFiles app serves `root` from.
    URL_PREFIX = "/files"

    def __init__(self, root: str = "./storage") -> None:
        self._root = Path(root).resolve()

    def put(self, path: str, data: bytes, content_type: str | None = None) -> StoredFileRef:
        key = path.lstrip("/")
        target = self._root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredFileRef(path=key, url=self.url(key))

    def url(self, path: str) -> str:
        return f"{self.URL_PREFIX}/{path.lstrip('/')}"
