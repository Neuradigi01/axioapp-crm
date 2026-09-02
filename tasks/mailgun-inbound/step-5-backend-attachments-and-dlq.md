# Step 5 — Attachments (two-phase write, MIME allowlist, libmagic sniff) + download endpoint + orphan sweeper + DLQ admin endpoint

**Status:** Pending
**Effort:** ~0.75 day
**Depends on:** Step 4 (`process_mailgun_inbound` task).
**Blocks:** Step 7 (end-to-end smoke with attachments).

## Goal

Extend the Mailgun ingest to handle attachments safely: two-phase write (staging → messages/), MIME allowlist enforced against libmagic-sniffed type, path traversal guarded, size caps, orphan sweeper.

Add the attachment download endpoint (new — no `/api/v1/files/` exists today) with `Content-Disposition: attachment` forced for all types.

Ship DLQ admin endpoint.

## Scope

**Attachment extractor** — `api/src/app/core/email/mailgun/service.py`:

```python
ALLOWED_MIME = frozenset({
    "text/plain", "text/csv",
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
})
PER_FILE_MAX = 10 * 1024 * 1024   # 10 MB
PER_MSG_MAX = 25 * 1024 * 1024    # 25 MB
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "attachment.bin")
    return SAFE_NAME_RE.sub("_", base)[:255] or "attachment.bin"

async def extract_and_stage_attachments(pending_dir: Path, org_id: uuid.UUID, request_uuid: uuid.UUID) -> tuple[list[dict], str | None]:
    """Move validated attachments from pending-inbound/ to staging/ and return metadata."""
    staging_dir = Path(STORAGE_ROOT) / str(org_id) / "staging" / str(request_uuid)
    staging_dir.mkdir(parents=True, exist_ok=True)

    attachments = []
    total_bytes = 0
    stripped_reason: str | None = None
    seen_names: dict[str, int] = {}

    for raw_path in sorted(pending_dir.glob("attachment_*")):
        size = raw_path.stat().st_size
        if size > PER_FILE_MAX:
            stripped_reason = "size_exceeded"
            continue
        if total_bytes + size > PER_MSG_MAX:
            stripped_reason = "size_exceeded"
            continue
        sniffed = magic.from_file(str(raw_path), mime=True)
        if sniffed not in ALLOWED_MIME:
            stripped_reason = "mime_disallowed"
            continue

        # Disambiguate name collisions.
        declared = raw_path.name.split("_", 2)[-1]  # attachment_<idx>_<name>
        safe = _sanitize_filename(declared)
        base, ext = os.path.splitext(safe)
        seen = seen_names.get(safe, 0) + 1
        if seen > 1:
            safe = f"{base}-{seen}{ext}"
        seen_names[safe] = seen

        dst = staging_dir / safe
        raw_path.rename(dst)
        total_bytes += size
        attachments.append({
            "filename": safe,
            "size": size,
            "content_type": sniffed,
            "storage_key": safe,   # relative to messages/{message_id}/
            "storage_backend": "local",
        })

    return attachments, stripped_reason

async def commit_attachments(staging_dir: Path, org_id: uuid.UUID, message_id: uuid.UUID) -> None:
    """Move staging → messages/ after Message row commits."""
    final_dir = Path(STORAGE_ROOT) / str(org_id) / "messages" / str(message_id)
    final_dir.mkdir(parents=True, exist_ok=True)
    for f in staging_dir.iterdir():
        f.rename(final_dir / f.name)
    staging_dir.rmdir()
```

**Wire into `process_mailgun_inbound`** (Step 4's task):

```python
request_uuid = uuid.UUID(path.name)  # pending-inbound dir name IS a uuid
attachments_meta, stripped = await extract_and_stage_attachments(path, sender.org_id, request_uuid)
if stripped:
    payload_meta = {"attachment_stripped_reason": stripped}
else:
    payload_meta = {}

message = await _persist_inbound_email(
    ...,
    attachments=attachments_meta,
    ...,
)
if message and attachments_meta:
    staging_dir = Path(STORAGE_ROOT) / str(sender.org_id) / "staging" / str(request_uuid)
    await commit_attachments(staging_dir, sender.org_id, message.id)
```

**Download endpoint** — `api/src/app/core/conversations/router.py`:

```python
DOWNLOAD_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]{1,255}$")

@router.get("/messages/{message_id}/attachments/{safe_key}")
async def download_message_attachment(
    message_id: uuid.UUID,
    safe_key: str,
    db: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_auth),
):
    if not DOWNLOAD_SAFE_KEY.match(safe_key):
        raise HTTPException(status_code=400, detail="invalid attachment key")

    msg = await messages_service.get_by_id_and_org(db, message_id=message_id, org_id=ctx.org_id)
    if msg is None:
        raise HTTPException(status_code=404)

    if not any(a.get("storage_key") == safe_key for a in (msg.attachments or [])):
        raise HTTPException(status_code=404)

    path = Path(STORAGE_ROOT) / str(msg.org_id) / "messages" / str(msg.id) / safe_key
    if not path.exists():
        raise HTTPException(status_code=404)

    # Force attachment disposition regardless of MIME.
    return FileResponse(
        path,
        headers={"Content-Disposition": f'attachment; filename="{safe_key}"'},
        media_type="application/octet-stream",  # override sniff; force download
    )
```

**Orphan sweepers** — `api/src/app/core/email/mailgun/orphan_cleanup.py`:

```python
async def sweep_staging_orphans():
    """Staging dirs > 1h old with no matching in-flight ingest → delete."""
    # Scan STORAGE_ROOT/*/staging/*/, delete dirs where mtime < now - 3600.

async def sweep_messages_orphans():
    """messages/{msg_id}/ dirs where no tbl_messages row exists > 24h old → delete."""
    # Scan STORAGE_ROOT/*/messages/*/, for each dir extract msg_id, check row exists.
    # If dir mtime < now - 86400 AND no row → delete.
```

Beat entries: `staging-orphan-sweep` every 15 min; `messages-orphan-sweep` daily.

**DLQ admin endpoint** — new `core/email/mailgun/router.py`:

```python
@router.get("/admin/email-inbound-dlq", dependencies=[Depends(require_owner)])
async def list_dlq(...):
    # Owner role only. Paginated. Org-scoped except platform-admin sees all.

@router.post("/admin/email-inbound-dlq/{id}/reprocess", dependencies=[Depends(require_owner)])
async def reprocess_dlq(...):
    # Re-enqueue the pending-inbound path. Mark resolved on success.
```

## Files touched

- `api/src/app/core/email/mailgun/service.py` — extract_and_stage, commit_attachments, sweepers.
- `api/src/app/core/email/mailgun/tasks.py` — wire attachments into ingest.
- `api/src/app/core/email/mailgun/orphan_cleanup.py` (new).
- `api/src/app/core/email/mailgun/router.py` — DLQ admin endpoints.
- `api/src/app/core/conversations/router.py` — attachment download endpoint.
- `api/src/app/core/conversations/service.py` — `get_by_id_and_org` if not already there.
- `api/src/app/shared/celery_config.py` — orphan-sweep beat entries.

## Tests

- `test_attachment_written_to_staging_first`
- `test_attachment_moved_to_messages_only_after_commit`
- `test_attachment_metadata_appended_to_jsonb`
- `test_attachment_over_10mb_rejected_and_stripped`
- `test_attachment_total_over_25mb_stripped_message_preserved`
- `test_attachment_mime_not_in_allowlist_rejected`
- `test_attachment_text_html_rejected_from_allowlist`
- `test_attachment_libmagic_sniff_wins_over_declared_content_type`
- `test_attachment_filename_path_traversal_sanitised`
- `test_attachment_filename_collision_gets_numeric_suffix`
- `test_attachment_staging_orphan_cleaned_after_1h`
- `test_attachment_messages_orphan_cleaned_after_24h`
- `test_attachment_sweeper_does_not_race_in_flight_ingest`
- `test_attachment_download_endpoint_requires_jwt`
- `test_attachment_download_endpoint_enforces_org_scope_returns_404_cross_org`
- `test_attachment_download_endpoint_forces_content_disposition_attachment`
- `test_attachment_download_safe_key_regex_rejects_path_traversal`
- `test_attachment_download_returns_404_when_key_not_in_message_attachments`
- `test_dlq_list_endpoint_owner_only_returns_403_for_admin`
- `test_dlq_list_endpoint_paginated`
- `test_dlq_reprocess_re_enqueues_and_marks_resolved`
- `test_dlq_list_org_scoped_no_cross_org_leak`

## Self-check

- [ ] Two-phase write: staging → messages/ ONLY after Message commit.
- [ ] `libmagic` sniff-type used for allowlist, NOT declared Content-Type.
- [ ] `text/html` NOT in allowlist.
- [ ] `text/*` glob NOT used; explicit list only.
- [ ] Download endpoint `Content-Disposition: attachment` for EVERY type (no `inline`).
- [ ] Download endpoint `safe_key` regex rejects `../`, `/`, `\`, control chars.
- [ ] Download endpoint 404s (not 403) on cross-org access.
- [ ] Sweeper cleans staging > 1h, messages/ > 24h — different cadences.
- [ ] DLQ endpoint Owner-only.

## Report template

```
Files changed: <list>

Manual verify (staging):
  1. Send an inbound with a 5MB PDF attachment → stored under messages/<id>/, downloadable.
  2. Send with 12MB PDF → stripped, message persists with `attachment_stripped_reason=size_exceeded`.
  3. Send with `.exe` renamed to `image.png` → sniff catches, rejected.
  4. Send with filename `../../etc/passwd` → sanitized to `..__..__etc__passwd`.
  5. GET /api/v1/messages/{id}/attachments/{key} with wrong-org JWT → 404.
  6. Force a Celery task failure 4 times → DLQ row appears. Owner sees via admin endpoint. Admin (non-Owner) 403.

Tests: 22 pytest.

Self-check: all pass.

Awaiting proceed for Step 6.
```
