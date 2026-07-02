"""Smoke: exercise the call recording upload + retrieval round-trip.

1. Seed a Call row for Ajay's Workspace.
2. Attach a tiny fake audio file via `attach_recording_file`.
3. Read it back via `read_recording_file` — verify bytes + MIME.
4. Cleanup the row.

Runs everything through the service layer (bypasses HTTP but exercises
the exact same code path the router uses).
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime

AJAY_ORG = uuid.UUID("41f9ede9-41b3-44ce-b489-3004566d4068")


async def main() -> None:
    from sqlalchemy import text as sql_text

    # Eagerly import so string-based FK ('tbl_organizations.id') resolves.
    from src.app.core.tenants import models as _tenants  # noqa: F401
    from src.app.core.calls import service as _calls_service
    from src.app.core.calls.models import Call, CallDirection
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    tk = set_context(RequestContext(org_id=AJAY_ORG, user_id=None))
    try:
        # 1. Seed a Call row.
        call_id: uuid.UUID
        async with async_session() as session:
            c = Call(
                org_id=AJAY_ORG,
                direction=CallDirection.out,
                started_at=datetime.now(UTC),
                duration_sec=42,
                notes="[smoke] recording round-trip",
            )
            session.add(c)
            await session.commit()
            await session.refresh(c)
            call_id = c.id
            print(f"created call: {call_id}")

        # 2. Upload a tiny fake audio blob.
        fake_mp3 = b"ID3\x04\x00\x00\x00" + b"\x00" * 32  # 39-byte "audio"
        async with async_session() as session:
            call = await _calls_service.attach_recording_file(
                session,
                call_id=call_id,
                filename="smoke.mp3",
                data=fake_mp3,
                content_type="audio/mpeg",
            )
            print(f"attached: recording_file_path = {call.recording_file_path}")

        # 3. Read it back.
        async with async_session() as session:
            data, ct = await _calls_service.read_recording_file(session, call_id=call_id)
            print(f"read back: {len(data)} bytes · content-type={ct}")
            assert data == fake_mp3, "byte mismatch!"
            assert ct == "audio/mpeg", f"unexpected mime: {ct}"

        # 4. Verify file lives on disk under the right path.
        from pathlib import Path
        expected = Path("./storage") / call.recording_file_path
        print(f"disk path: {expected} · exists={expected.exists()}")

        # 5. Test the size-cap guard.
        oversized = b"\x00" * (31 * 1024 * 1024)  # 31 MB
        async with async_session() as session:
            try:
                await _calls_service.attach_recording_file(
                    session, call_id=call_id, filename="huge.mp3",
                    data=oversized, content_type="audio/mpeg",
                )
                print("ERROR: oversized upload was NOT rejected")
            except Exception as ex:
                print(f"size guard OK: {type(ex).__name__} · {getattr(ex, 'detail', ex)}")

        # 6. Test the extension guard (mp4).
        async with async_session() as session:
            try:
                await _calls_service.attach_recording_file(
                    session, call_id=call_id, filename="clip.mp4",
                    data=fake_mp3, content_type="video/mp4",
                )
                print("ERROR: .mp4 was NOT rejected")
            except Exception as ex:
                print(f"ext guard OK: {type(ex).__name__} · {getattr(ex, 'detail', ex)}")

        # 7. Cleanup.
        async with async_session() as session:
            call = await _calls_service.get_call(session, call_id)
            await session.delete(call)
            await session.commit()
            print("cleanup: deleted smoke call row")
        # Also remove the file on disk.
        if expected.exists():
            expected.unlink()
            print("cleanup: removed smoke audio file from disk")
    finally:
        reset_context(tk)


asyncio.run(main())
