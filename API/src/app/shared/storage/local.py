"""Local-filesystem `StorageBackend`.

Blobs are written under `./storage/<key>` (resolved against the process
CWD) and served read-only by the `/files` static mount declared in
`main.py`. Disk IO runs in a worker thread so the event loop never
blocks on it.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from src.app.shared.storage.base import (
    DEFAULT_CHUNK_SIZE,
    MAX_DIRECTORY_OBJECTS,
    StorageBackend,
    StoredFileRef,
    StoredFileStat,
)
from src.app.shared.storage.keys import content_type_for, validate_key, validate_prefix


class LocalStorage(StorageBackend):
    """Disk-backed storage rooted at `root` (default `./storage`)."""

    #: Mount point the `/files` StaticFiles app serves `root` from.
    URL_PREFIX = "/files"

    def __init__(self, root: str = "./storage") -> None:
        self._root = Path(root).resolve()

    def _resolve_safe(self, path: str) -> Path:
        """Join a validated key to the storage root and refuse anything
        that would still escape it (e.g. through a symlink)."""
        target = (self._root / validate_key(path)).resolve()
        if target != self._root and self._root not in target.parents:
            raise ValueError(f"path {path!r} resolves outside storage root")
        return target

    def _resolve_prefix(self, prefix: str) -> Path:
        return self._resolve_safe(validate_prefix(prefix).rstrip("/"))

    async def put(self, path: str, data: bytes, content_type: str | None = None) -> StoredFileRef:
        target = self._resolve_safe(path)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(_write)
        return StoredFileRef(path=path, url=self.url(path))

    async def get(self, path: str) -> bytes:
        target = self._resolve_safe(path)
        return await asyncio.to_thread(target.read_bytes)

    async def open_stream(
        self, path: str, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        target = self._resolve_safe(path)
        handle = await asyncio.to_thread(target.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def stat(self, path: str) -> StoredFileStat:
        target = self._resolve_safe(path)
        st = await asyncio.to_thread(target.stat)
        if not target.is_file():
            raise FileNotFoundError(path)
        etag = hashlib.sha256(f"{st.st_size}-{st.st_mtime_ns}".encode()).hexdigest()[:32]
        return StoredFileStat(size=st.st_size, etag=etag, content_type=content_type_for(path))

    def url(self, path: str) -> str:
        return f"{self.URL_PREFIX}/{path}"

    async def delete(self, path: str) -> bool:
        target = self._resolve_safe(path)

        def _unlink() -> bool:
            if not target.is_file():
                return False
            target.unlink()
            return True

        return await asyncio.to_thread(_unlink)

    async def delete_directory(self, prefix: str) -> int:
        target = self._resolve_prefix(prefix)

        def _rmtree() -> int:
            if not target.is_dir():
                return 0
            count = sum(1 for p in target.rglob("*") if p.is_file())
            if count > MAX_DIRECTORY_OBJECTS:
                raise ValueError(
                    f"refusing to delete {count} objects under {prefix!r} "
                    f"(cap {MAX_DIRECTORY_OBJECTS})"
                )
            shutil.rmtree(target)
            return count

        return await asyncio.to_thread(_rmtree)

    async def list_keys(self, prefix: str) -> AsyncIterator[str]:
        target = self._resolve_prefix(prefix)

        def _walk() -> list[str]:
            if not target.is_dir():
                return []
            return sorted(
                p.relative_to(self._root).as_posix() for p in target.rglob("*") if p.is_file()
            )

        for key in await asyncio.to_thread(_walk):
            yield key
