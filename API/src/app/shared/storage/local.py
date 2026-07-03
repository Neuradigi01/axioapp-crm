"""Local-filesystem `StorageBackend`.

Blobs are written under `./storage/<key>` (resolved against the process
CWD) and served read-only by the `/files` static mount declared in
`main.py`. The `./storage` root is the same one the import readers join
their relative paths onto, so writes here are visible to those readers.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.app.shared.storage.base import StorageBackend, StoredFileRef


class LocalStorage(StorageBackend):
    """Disk-backed storage rooted at `root` (default `./storage`)."""

    #: Mount point the `/files` StaticFiles app serves `root` from.
    URL_PREFIX = "/files"

    def __init__(self, root: str = "./storage") -> None:
        self._root = Path(root).resolve()

    def _resolve_safe(self, path: str) -> Path:
        """Join `path` to the storage root and refuse anything that
        would escape it (path traversal via `..` / absolute paths)."""
        key = path.lstrip("/")
        target = (self._root / key).resolve()
        if target != self._root and self._root not in target.parents:
            raise ValueError(f"path {path!r} resolves outside storage root")
        return target

    def put(self, path: str, data: bytes, content_type: str | None = None) -> StoredFileRef:
        target = self._resolve_safe(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        key = path.lstrip("/")
        return StoredFileRef(path=key, url=self.url(key))

    def url(self, path: str) -> str:
        return f"{self.URL_PREFIX}/{path.lstrip('/')}"

    def delete(self, path: str) -> bool:
        target = self._resolve_safe(path)
        if not target.is_file():
            return False
        target.unlink()
        return True

    def delete_directory(self, prefix: str) -> int:
        target = self._resolve_safe(prefix)
        if not target.exists() or not target.is_dir():
            return 0
        count = sum(1 for p in target.rglob("*") if p.is_file())
        shutil.rmtree(target)
        return count
