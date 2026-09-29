"""Copy blobs between local disk (``STORAGE_ROOT``) and the R2 bucket.

Operator command (``run storage-migrate``), used around a cutover:

    python -m src.app.shared.storage.migrate [--dry-run] [--only-missing] [--reverse]

* default — disk → R2. Copies a file when the object is absent or
  differs in size / MD5. Run BEFORE flipping ``STORAGE_BACKEND=r2``.
* ``--only-missing`` — copy only keys the destination lacks; never
  overwrite. Run AFTER the flip (and after every container restarted)
  to catch files written to disk in between, without clobbering a newer
  copy uploaded to R2 since.
* ``--reverse`` — R2 → disk, the rollback path. Every bucket key passes
  the key guard and `LocalStorage`'s root check, so a hostile key can
  never write outside ``STORAGE_ROOT``.
* ``--dry-run`` — report what would be copied; write nothing.

Never copied: the short-lived Mailgun folders (``pending-inbound/``,
``pending-events/``, ``{org}/staging/``) and symlinks. Idempotent and
resumable; a lock file refuses a second concurrent run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from src.app.shared.storage.config import r2_settings, storage_root
from src.app.shared.storage.keys import content_type_for, validate_key
from src.app.shared.storage.local import LocalStorage
from src.app.shared.storage.r2 import R2Storage

logger = logging.getLogger(__name__)

_SKIPPED_TOP_LEVEL = frozenset({"pending-inbound", "pending-events"})
_LOCK_NAME = ".storage-migrate.lock"


@dataclass
class MigrationReport:
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_copied: int = 0

    def summary(self, *, dry_run: bool) -> str:
        verb = "would copy" if dry_run else "copied"
        return (
            f"{verb}={self.copied} skipped={self.skipped} failed={self.failed} "
            f"bytes={self.bytes_copied}"
        )


def is_migratable_key(key: str) -> bool:
    """False for Mailgun temp folders and anything the key guard rejects."""
    try:
        validate_key(key)
    except ValueError:
        return False
    parts = key.split("/")
    if parts[0] in _SKIPPED_TOP_LEVEL or parts[0].startswith("."):
        return False
    return not (len(parts) > 1 and parts[1] == "staging")


def iter_disk_keys(root: Path) -> list[tuple[str, Path]]:
    """Every regular, non-symlink file under `root` as ``(key, path)``.
    Symlinked directories are not descended into."""
    found: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not (base / d).is_symlink()]
        for name in filenames:
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            key = path.relative_to(root).as_posix()
            if is_migratable_key(key):
                found.append((key, path))
    return sorted(found)


async def migrate_to_r2(
    local_root: Path, r2: R2Storage, *, dry_run: bool, only_missing: bool
) -> MigrationReport:
    report = MigrationReport()
    for key, path in iter_disk_keys(local_root):
        try:
            data = await asyncio.to_thread(path.read_bytes)
            remote = await r2.raw_etag(key)
            if remote is not None and (
                only_missing or remote == hashlib.md5(data, usedforsecurity=False).hexdigest()
            ):
                report.skipped += 1
                continue
            if not dry_run:
                await r2.put(key, data, content_type=content_type_for(key))
            report.copied += 1
            report.bytes_copied += len(data)
        except Exception:
            logger.exception("storage-migrate: failed %s", key)
            report.failed += 1
    return report


async def migrate_to_disk(
    r2: R2Storage, local: LocalStorage, local_root: Path, *, dry_run: bool, only_missing: bool
) -> MigrationReport:
    report = MigrationReport()
    for key in await r2.list_all_keys():
        if not is_migratable_key(key):
            report.skipped += 1
            continue
        try:
            target = local_root / key
            if only_missing and target.exists():
                report.skipped += 1
                continue
            data = await r2.get(key)
            if not only_missing and target.is_file() and target.read_bytes() == data:
                report.skipped += 1
                continue
            if not dry_run:
                await local.put(key, data)
            report.copied += 1
            report.bytes_copied += len(data)
        except Exception:
            logger.exception("storage-migrate: failed %s", key)
            report.failed += 1
    return report


class MigrationLocked(RuntimeError):
    """Another storage-migrate run holds the lock."""


def _acquire_lock(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    lock = root / _LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise MigrationLocked(
            f"{lock} exists — another storage-migrate is running. "
            "Delete the file only if you are sure it is not."
        ) from exc
    with os.fdopen(fd, "w") as handle:
        handle.write(str(os.getpid()))
    return lock


async def run(*, dry_run: bool, only_missing: bool, reverse: bool) -> MigrationReport:
    root = storage_root().resolve()
    r2 = R2Storage(r2_settings())
    lock = _acquire_lock(root)
    try:
        if reverse:
            return await migrate_to_disk(
                r2, LocalStorage(root=str(root)), root, dry_run=dry_run, only_missing=only_missing
            )
        return await migrate_to_r2(root, r2, dry_run=dry_run, only_missing=only_missing)
    finally:
        lock.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storage-migrate", description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    direction = "R2 -> disk" if args.reverse else "disk -> R2"
    settings = r2_settings()
    print(f"storage-migrate: {direction} bucket={settings.bucket} root={storage_root().resolve()}")
    report = asyncio.run(
        run(dry_run=args.dry_run, only_missing=args.only_missing, reverse=args.reverse)
    )
    print(f"storage-migrate: {report.summary(dry_run=args.dry_run)}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
