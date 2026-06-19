# Step 5 — Outbound media send (image, video, audio, document)

**Goal:** Lift the "media uploads are deferred" block from the WhatsApp send path. Customer can attach image / video / audio / document to a conversation message via the composer, file uploads to Meta Graph API's media endpoint, returned `media_id` ships in the outbound message payload, and recipient receives the rich media on WhatsApp.
**Status:** COMPLETED
**Depends on:** Step 4 (Phase 1 closed — connected ES org with valid long-lived token).

---

## Scope

In-scope:
- Backend extension to existing `POST /api/v1/conversations/{id}/messages` to accept `attachment: { type: 'image'|'video'|'audio'|'document', file_id: <uuid> }`.
- New service `media_upload.py` — uploads to `POST /{phone_id}/media`, captures `media_id`, sends message with `type: image|video|audio|document` and `id: <media_id>`.
- Storage via existing `StorageBackend` at `./storage/{org_id}/whatsapp_media/{file_id}` per CLAUDE.md storage rules.
- File validation: image ≤5MB, video ≤16MB, audio ≤16MB, document ≤100MB (Meta limits). MIME type whitelist enforced server-side.
- Webhook receives delivery / read status as before — no change.
- Conversation composer: paperclip → file picker → preview (thumb for image/video, file card for doc) → optional caption → send.
- Drag-and-drop into composer area.
- Progress indicator during upload to Meta.
- Inline rendering of sent media in the thread reusing existing inbound media rendering.

Out of scope:
- Outbound location share, contact card share — Step 28.
- Outbound stickers — Step 28.
- Media transcoding / compression — relies on Meta's tolerance + frontend pre-validation.

## Files to touch

| File | Action |
|---|---|
| [`API/src/app/core/conversations/adapters/whatsapp.py`](API/src/app/core/conversations/adapters/whatsapp.py) | Remove "media uploads deferred" comment; extend `send()` to handle attachment payloads |
| `API/src/app/core/conversations/media_upload.py` | **NEW** — Meta media upload + media_id capture |
| [`API/src/app/core/conversations/router.py`](API/src/app/core/conversations/router.py) | Extend message-create endpoint to accept `attachment` field |
| [`API/src/app/core/conversations/schemas.py`](API/src/app/core/conversations/schemas.py) | Add `AttachmentPayload` Pydantic model |
| `APP/.../conversations/composer/composer.component.ts` | Add paperclip + drag-and-drop + file picker + caption input |
| `APP/.../conversations/composer/media-preview.component.ts` | **NEW** — preview tile before send |
| `APP/.../conversations/conversations.service.ts` | Add upload helper that uses existing files endpoint then includes file_id in message payload |
| `API/tests/conversations/test_whatsapp_send_media.py` | **NEW** — mocked Meta media endpoint + status path coverage |

**~8 files. ~350 lines net.**

## Plan

1. Read existing `whatsapp.py` adapter to confirm send signature + how text/template send is structured.
2. Build `media_upload.py`:
   ```python
   async def upload_media_to_meta(phone_id, token, file_path, mime_type) -> str:
       # POST {phone_id}/media multipart with file + messaging_product=whatsapp
       # returns Meta media_id
   ```
3. Extend `WhatsAppAdapter.send()` — if `attachment` present, upload first, then send `type` + `id`. Caption goes in same payload for image/video/document.
4. Add `AttachmentPayload` schema with type + file_id + caption (optional, max length per Meta).
5. Extend router validation: ensure file belongs to org (RLS); reject if MIME not in whitelist; reject if file exceeds per-type size limit.
6. Frontend composer: import existing file-upload service (used for email attachments); show preview before send; emit message with attachment.
7. Tests: mock Meta upload returning fake media_id; assert send payload shape per Meta spec; failure case (Meta returns 400 on oversized file).

## DB changes / migrations

**None.** Existing `tbl_conversation_messages.payload JSONB` already stores arbitrary outbound shape; attachment goes inside.

## Tests

Add `test_whatsapp_send_media.py` — 5 cases (each media type happy path + 2 failure paths).

## Smoke

```
1. Connect WhatsApp via Step-3 flow (Phase 1 complete).
2. Open a conversation. Paperclip → upload sofa.jpg (image). Add caption "New arrival." Send.
3. Verify on the recipient's WhatsApp: image arrives with caption.
4. Repeat for .mp4 (video), .pdf (document), .ogg (audio).
5. Try a 20MB image → composer rejects pre-upload with size message.
6. Try .exe file → composer rejects (MIME not in whitelist).
7. Delivery status icons (✓ → ✓✓) update via webhook as before.
```

## Risks

- **Meta media URL expires after 30 days.** Inbound media we cache locally; outbound is uploaded fresh each send — no expiry concern.
- **Upload-then-send is two API calls** — if first succeeds and second fails, media is orphaned at Meta. Acceptable; Meta GC's media after 30 days.
- **Caption length limits vary by media type** (image/video: 1024 chars; document: no caption support per Meta — UI must disable caption field for docs).

## Self-check (10 rules)

- [ ] Rule 1: All `core/conversations/`. No packs imports.
- [ ] Rule 2: Existing `tbl_conversation_messages` has org_id + RLS.
- [ ] Rule 3: Custom fields untouched.
- [ ] Rule 4: Composer is static, not custom-field-driven.
- [ ] Rule 5: No registry change.
- [ ] Rule 6: Reuses `conversations.send`.
- [ ] Rule 7: pack.yaml untouched.
- [ ] Rule 8: 8 files, ~350 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: Removes the existing "deferred" comment — no new TODOs.

## Stop & report

```
Step 5 — Outbound media send
Files: 8 (4 backend, 3 frontend, 1 test)
Verify: image/video/audio/document send + receive end-to-end; oversize + bad-MIME rejection; existing text/template send unaffected.
Tests: 5 pytest cases.
Self-check: 10 rules green.
Next: Step 6 — interactive messages (buttons / list).
Awaiting "proceed".
```
