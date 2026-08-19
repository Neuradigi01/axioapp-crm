"""Backend tests for the header profile-picture upload
(``tasks/ai-assistants`` Step 13).

Pure-Python validation cases fire the ``validate_image_upload``
helper directly (no DB); the end-to-end service test skips when
the compose stack isn't up.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import struct
import uuid
import zlib

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Side-effect imports so FK metadata resolves at query-compile time.
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402

from src.app.core.ai_assistants.file_upload import (
    FileValidationError,
    validate_image_upload,
)


def _install_kek() -> None:
    if os.environ.get("AI_PROVIDER_KEY_KEK"):
        return
    os.environ["AI_PROVIDER_KEY_KEK"] = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode()
    import config as app_config

    app_config.AI_PROVIDER_KEY_KEK = os.environ["AI_PROVIDER_KEY_KEK"]


_install_kek()


def _make_png(w: int = 1, h: int = 1) -> bytes:
    """Minimal-valid PNG bytes — 1x1 transparent pixel. Enough for
    ``filetype.guess()`` to recognise as ``image/png``."""
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = _chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0),  # RGBA, no interlace
    )
    raw = b"\x00" + b"\x00\x00\x00\x00" * w  # filter byte + 1 transparent pixel
    idat = _chunk(b"IDAT", zlib.compress(raw * h))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_jpeg() -> bytes:
    """Smallest valid-ish JPEG — starts with SOI + APP0 header so
    ``filetype`` sniffs image/jpeg."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00" + (b"\x08" * 64) + b"\xff\xd9"
    )


def _fake_svg() -> bytes:
    return b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


# --- Pure-Python validation cases ----------------------------------------


def test_empty_image_rejected() -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_image_upload(filename="a.png", data=b"")
    assert exc.value.reason == "empty_file"


def test_oversized_image_rejected() -> None:
    huge = _make_png() + b"\x00" * (2 * 1024 * 1024 + 1)
    with pytest.raises(FileValidationError) as exc:
        validate_image_upload(filename="big.png", data=huge)
    assert exc.value.reason == "image_too_large"


def test_svg_rejected() -> None:
    """SVG is refused because it can carry <script> — script injection
    via image opens is the whole reason we whitelist raster formats."""
    with pytest.raises(FileValidationError) as exc:
        validate_image_upload(filename="malicious.svg", data=_fake_svg())
    assert exc.value.reason == "unsupported_image_mime"


def test_pdf_renamed_to_png_rejected() -> None:
    """A PDF served with a .png extension: magic-byte sniff catches
    the mismatch + refuses."""
    fake_pdf = b"%PDF-1.4\n" + b"\x00" * 512 + b"%%EOF"
    with pytest.raises(FileValidationError) as exc:
        validate_image_upload(filename="innocent.png", data=fake_pdf)
    assert exc.value.reason == "unsupported_image_mime"


def test_valid_png_accepted() -> None:
    png = _make_png()
    result = validate_image_upload(filename="avatar.png", data=png)
    assert result.sniffed_mime == "image/png"
    assert result.extension == "png"
    assert result.size_bytes == len(png)
    assert result.content_hash == hashlib.sha256(png).digest()


def test_valid_jpeg_accepted() -> None:
    jpg = _make_jpeg()
    result = validate_image_upload(filename="photo.jpg", data=jpg)
    assert result.sniffed_mime == "image/jpeg"
    assert result.extension == "jpg"


def test_illegal_filename_rejected() -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_image_upload(filename="../../etc/passwd", data=_make_png())
    assert exc.value.reason == "illegal_filename_chars"


# --- Storage key naming --------------------------------------------------


def test_storage_key_never_uses_client_filename() -> None:
    """Same guarantee as knowledge uploads: client filename never
    used as a path component. The ``ts_ms`` bit is the versioned
    filename so CDN caches don't serve the prior avatar."""
    from src.app.core.ai_assistants import service as ai_service

    org = uuid.uuid4()
    aid = uuid.uuid4()
    key = ai_service._profile_picture_key(org, aid, ext="png", ts_ms=1_700_000_000_000)
    assert key == f"{org}/ai_assistants/{aid}/profile/1700000000000.png"
    assert ".." not in key


def test_url_to_key_roundtrip() -> None:
    from src.app.core.ai_assistants import service as ai_service

    assert ai_service._url_to_key("/files/foo/bar.png") == "foo/bar.png"
    assert ai_service._url_to_key("https://external.com/img.png") is None


# --- End-to-end service round-trip --------------------------------------


def _db_url() -> str | None:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, password, name]):
        return None
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


async def _set_rls(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :o, true)"),
        {"o": str(org_id)},
    )


async def _pick_org(session: AsyncSession) -> uuid.UUID | None:
    result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 1"))
    row = result.scalar_one_or_none()
    return uuid.UUID(str(row)) if row is not None else None


async def _insert_key(session: AsyncSession, *, org_id: uuid.UUID, label: str) -> uuid.UUID:
    kid = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tbl_ai_provider_keys
                (id, org_id, provider, label, encrypted_key, nonce,
                 key_version, fingerprint_sha256, last4, test_status)
            VALUES (:id, :org, 'openai', :label,
                    :ct, :nn, 1, :fp, 'test', 'untested')
            """
        ),
        {
            "id": str(kid),
            "org": str(org_id),
            "label": label,
            "ct": secrets.token_bytes(64),
            "nn": secrets.token_bytes(12),
            "fp": secrets.token_bytes(32),
        },
    )
    return kid


async def _cleanup(session: AsyncSession, *, key_ids: list[uuid.UUID]) -> None:
    await session.execute(
        text("DELETE FROM tbl_ai_assistants WHERE key_id = ANY(:k)"),
        {"k": [str(k) for k in key_ids]},
    )
    for kid in key_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
            {"id": str(kid)},
        )
    await session.commit()


async def test_upload_and_delete_profile_picture_end_to_end() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    keys: list[uuid.UUID] = []
    async with Session() as session:
        org = await _pick_org(session)
        if org is None:
            await engine.dispose()
            pytest.skip("No organization to test against")
        await _set_rls(session, org)
        kid = await _insert_key(session, org_id=org, label="profile-pic-smoke")
        keys.append(kid)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        try:
            await _set_rls(session, org)
            uniq = uuid.uuid4().hex[:8]
            created = await ai_service.create_assistant(
                session,
                org_id=org,
                user_id=None,
                payload=AiAssistantCreate(
                    name=f"profile-pic-{uniq}",
                    key_id=kid,
                    model="gpt-4o-mini",
                ),
            )
            # Upload path — persists URL onto styling_config JSONB.
            png = _make_png()
            result = await ai_service.upload_profile_picture(
                session,
                org_id=org,
                assistant_id=created.id,
                filename="avatar.png",
                data=png,
            )
            assert result["url"].startswith("/files/")
            assert f"{created.id}/profile/" in result["url"]

            # Re-read to confirm styling_config was updated.
            reloaded = await ai_service.get_assistant(
                session, org_id=org, assistant_id=created.id
            )
            assert reloaded.styling_config["header_profile_picture_url"] == result["url"]

            # SVG rejection at the service layer surfaces as 422.
            with pytest.raises(HTTPException) as exc:
                await ai_service.upload_profile_picture(
                    session,
                    org_id=org,
                    assistant_id=created.id,
                    filename="evil.svg",
                    data=_fake_svg(),
                )
            assert exc.value.status_code == 422
            assert exc.value.detail["reason"] == "unsupported_image_mime"

            # Delete clears the key without touching sibling keys.
            await ai_service.delete_profile_picture(
                session,
                org_id=org,
                assistant_id=created.id,
            )
            reloaded2 = await ai_service.get_assistant(
                session, org_id=org, assistant_id=created.id
            )
            assert "header_profile_picture_url" not in (reloaded2.styling_config or {})
        finally:
            reset_context(tok)
            await _cleanup(session, key_ids=keys)
    await engine.dispose()
