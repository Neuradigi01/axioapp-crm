"""Cloudflare R2 `StorageBackend` (S3-compatible API via boto3).

The bucket is private: nothing is served from R2 directly. Blobs are
read back through the API (`/files/...` and the authenticated download
endpoints), so `url()` keeps the same server-relative shape as
`LocalStorage` and no stored URL changes when a deployment switches
backend.

boto3 is synchronous. Every call runs on this backend's own bounded
thread pool — never the default executor — so a slow R2 can only
exhaust storage threads, not the ones other `asyncio.to_thread` users
share.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.app.shared.storage.base import (
    DEFAULT_CHUNK_SIZE,
    MAX_DIRECTORY_OBJECTS,
    StorageBackend,
    StoredFileRef,
    StoredFileStat,
)
from src.app.shared.storage.config import R2Settings
from src.app.shared.storage.keys import content_type_for, validate_key, validate_prefix

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Size of the dedicated storage thread pool (and boto3's HTTP pool).
MAX_WORKERS = 16

#: S3 `DeleteObjects` accepts at most 1,000 keys per request.
_DELETE_BATCH = 1000

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


def _client_config() -> Config:
    return Config(
        signature_version="s3v4",
        connect_timeout=5,
        read_timeout=30,
        retries={"max_attempts": 3, "mode": "standard"},
        max_pool_connections=MAX_WORKERS,
        # Newer botocore sends CRC32 checksum headers on every request by
        # default; only send / validate them where the operation requires.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES


def _opaque_etag(etag: str) -> str:
    return hashlib.sha256(etag.strip('"').encode()).hexdigest()[:32]


class R2Storage(StorageBackend):
    """Blobs in one private R2 bucket, keyed exactly like `LocalStorage`."""

    #: Same server-relative prefix `LocalStorage` uses.
    URL_PREFIX = "/files"

    def __init__(self, settings: R2Settings, *, client: Any | None = None) -> None:
        self._bucket = settings.bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name="auto",
            config=_client_config(),
        )
        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="r2")

    @property
    def bucket(self) -> str:
        return self._bucket

    async def _run(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))

    async def _head(self, key: str) -> dict[str, Any]:
        try:
            return await self._run(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise FileNotFoundError(key) from exc
            raise

    async def put(self, path: str, data: bytes, content_type: str | None = None) -> StoredFileRef:
        key = validate_key(path)
        await self._run(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type or content_type_for(key),
        )
        return StoredFileRef(path=key, url=self.url(key))

    async def get(self, path: str) -> bytes:
        key = validate_key(path)

        def _get() -> bytes:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    raise FileNotFoundError(key) from exc
                raise
            with response["Body"] as body:
                return body.read()

        return await self._run(_get)

    async def open_stream(
        self, path: str, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        key = validate_key(path)
        try:
            response = await self._run(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise FileNotFoundError(key) from exc
            raise
        body = response["Body"]
        try:
            while chunk := await self._run(body.read, chunk_size):
                yield chunk
        finally:
            await self._run(body.close)

    async def stat(self, path: str) -> StoredFileStat:
        key = validate_key(path)
        head = await self._head(key)
        return StoredFileStat(
            size=int(head["ContentLength"]),
            etag=_opaque_etag(head.get("ETag", "")),
            content_type=head.get("ContentType") or content_type_for(key),
        )

    def url(self, path: str) -> str:
        return f"{self.URL_PREFIX}/{path}"

    async def delete(self, path: str) -> bool:
        key = validate_key(path)
        try:
            await self._head(key)
        except FileNotFoundError:
            return False
        await self._run(self._client.delete_object, Bucket=self._bucket, Key=key)
        return True

    async def _list_raw(self, prefix: str, limit: int | None = None) -> list[str]:
        """Every key under an already-validated `prefix`, stopping once
        `limit` keys are collected."""
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = await self._run(self._client.list_objects_v2, **kwargs)
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
            if limit is not None and len(keys) >= limit:
                return keys[:limit]
            if not page.get("IsTruncated"):
                return keys
            token = page.get("NextContinuationToken")

    async def delete_directory(self, prefix: str) -> int:
        scoped = validate_prefix(prefix)
        keys = await self._list_raw(scoped, limit=MAX_DIRECTORY_OBJECTS + 1)
        if len(keys) > MAX_DIRECTORY_OBJECTS:
            raise ValueError(
                f"refusing to delete more than {MAX_DIRECTORY_OBJECTS} objects under {prefix!r}"
            )
        for start in range(0, len(keys), _DELETE_BATCH):
            batch = keys[start : start + _DELETE_BATCH]
            result = await self._run(
                self._client.delete_objects,
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
            if errors := result.get("Errors"):
                raise RuntimeError(f"R2 refused to delete {len(errors)} object(s) under {prefix!r}")
        return len(keys)

    async def list_keys(self, prefix: str) -> AsyncIterator[str]:
        for key in await self._list_raw(validate_prefix(prefix)):
            try:
                yield validate_key(key)
            except ValueError:
                logger.warning("r2: skipping unsafe key in bucket listing: %r", key)

    async def check_reachable(self) -> None:
        await self._run(self._client.head_bucket, Bucket=self._bucket)

    # --- Migration helpers (`storage-migrate` only) --------------------

    async def raw_etag(self, path: str) -> str | None:
        """The object's S3 ETag without quotes, or None when absent. For
        single-part uploads it is the content MD5."""
        try:
            head = await self._head(validate_key(path))
        except FileNotFoundError:
            return None
        return str(head.get("ETag", "")).strip('"')

    async def list_all_keys(self) -> list[str]:
        """Every key in the bucket, unscoped. Used only by the operator
        migration command; unsafe keys are dropped with a warning."""
        safe: list[str] = []
        for key in await self._list_raw(""):
            try:
                safe.append(validate_key(key))
            except ValueError:
                logger.warning("r2: skipping unsafe key in bucket listing: %r", key)
        return safe
