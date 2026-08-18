# Step 10 — Knowledge Source backend — file + custom text + URL + Celery ingest

**Goal:** Ship backend endpoints and Celery pipeline for all three knowledge source types (file, custom text, URL). File uploads are magic-byte-sniffed and stored at `{knowledge_id}.bin` (never client filename). URL fetches reject RFC1918 IPs per hop. Ingest task chunks + embeds + upserts through `shared/vector/`, writes a heartbeat every 30s. Content-hash dedup rejects re-uploads. Cancellation and replace flows supported. Retrieval query already wired in Step 9 will start returning real results once knowledge is ingested.
**Status:** Pending
**Depends on:** Steps 2 (LLMClient.embed), 4 (VectorStore + chunker), 5 (tables), 9 (runtime uses retrieved chunks).

---

## Scope

In-scope:

- `core/ai_assistants/ingest.py` — Celery task target:
  - `@shared_task(bind=True, max_retries=3) async def ingest_knowledge(self, knowledge_id, org_id)` — loads row, dispatches by `source_type`:
    - `file`: read from `StorageBackend.get({knowledge_id}.bin)`; PDF via `pdfplumber` (JS + external refs disabled), TXT via UTF-8 decode with BOM strip.
    - `text`: read from `body_text` column.
    - `url`: HTTP GET via `httpx.AsyncClient(follow_redirects=True, timeout=30)`; DNS resolve per redirect + reject RFC1918 / link-local / loopback; content-type check (accept `text/html`, `text/plain`, `application/pdf`); HTML → readability extraction via `readability-lxml`; PDF → same path as file.
  - Common pipeline:
    - Update `progress_pct=10`, `status='processing'`, `heartbeat_at=now()`.
    - Extract text; if empty → `status='failed_no_text'`, message set.
    - Check `pending_delete` / `pending_cancel` — abort if so.
    - `chunker.chunk_text(text)` → chunks.
    - `progress_pct=40`. Heartbeat.
    - Batch embed via `LLMClient.embed(chunks_texts, batch_size=100)`.
    - `progress_pct=80`. Heartbeat.
    - `VectorStore.upsert(entries)` for each chunk — INSERT via DAL inside a single transaction; on conflict re-upsert.
    - `progress_pct=100`, `status='ready'`, `chunk_count=len(chunks)`, `heartbeat_at=null`.
  - Heartbeat every 30s during long ops via a lightweight `heartbeat_pulse(knowledge_id)` DAL call.
  - Cancellation check between chunk batches: `SELECT status FROM tbl_ai_assistant_knowledge WHERE id=:id FOR UPDATE` — if `pending_cancel`, delete inserted chunks + set `status='failed_ingest'`.
- `core/ai_assistants/file_upload.py` — small helper for the upload endpoint:
  - Magic-byte sniff (`filetype` library or manual header check): reject if declared MIME ≠ sniffed type.
  - Windows-reserved-name check on `original_filename` (`CON`, `NUL`, `AUX`, `PRN`, `COM1-9`, `LPT1-9`) — reject with 422.
  - Compute `sha256(file_bytes)` for `content_hash`.
  - Enforce size cap (< 90 MB raw upload); enforce decoded-text cap (< 20 MB after extraction).
  - Zip-bomb heuristic: reject files whose decompressed-to-compressed ratio > 100x.
- Router endpoints in `core/ai_assistants/router.py`:
  - `POST /ai-assistants/{id}/knowledge/file` — `multipart/form-data`; body: `file: UploadFile`. Saves via `StorageBackend.put(org_id/ai_assistants/{knowledge_id}.bin, ...)`, computes hash, creates row with `status='pending'`, dispatches Celery `ingest_knowledge.delay(...)`. Dedup: if row with same `(assistant_id, content_hash)` exists, return existing row instead of creating.
  - `POST /ai-assistants/{id}/knowledge/text` — body `{title, body_text}`. Same hash-based dedup.
  - `POST /ai-assistants/{id}/knowledge/url` — body `{url, title}`. Validates URL scheme (`http`/`https` only); DNS resolves + rejects private IPs BEFORE creating the row. Creates row and dispatches.
  - `GET /ai-assistants/{id}/knowledge` — list with status + progress.
  - `DELETE /ai-assistants/{id}/knowledge/{kid}` — marks `pending_delete`, dispatches cleanup (removes storage file, chunks via cascade).
  - `POST /ai-assistants/{id}/knowledge/{kid}/cancel` — marks `pending_cancel` (only valid if `status='processing'`).
  - `POST /ai-assistants/{id}/knowledge/{kid}/replace` — accepts a new upload, ingests to a temporary row, on success deletes the old row's chunks (never a nothing-in-between window).
- Data-access additions: `insert_knowledge`, `get_knowledge_for_update`, `set_status`, `set_progress`, `heartbeat_pulse`, `list_knowledge_by_assistant`, `upsert_chunks_batch`, `delete_knowledge_and_chunks`.
- Storage: `StorageBackend` already exists per CLAUDE.md; store at `{org_id}/ai_assistants/{knowledge_id}.bin`. Serving stored files (rare — mostly internal-only) uses `Content-Disposition: attachment` + `X-Content-Type-Options: nosniff`.
- Celery task registration in `core/ai_assistants/tasks.py`.
- **Add exception-list entry** for `core/ai_assistants/ingest.py` in [API/tests/test_layered_architecture_convention.py](API/tests/test_layered_architecture_convention.py) (already added in Step 5).
- SSRF-defence helper `shared/http/safe_fetch.py` — `safe_fetch(url, ...)` that DNS-resolves + rejects private, checks per-hop on redirect (reusable across future URL-fetching features).

Out of scope:
- Knowledge tab UI (Step 11).
- Reaper for stuck ingest (Step 17).
- Long-term retention (Step 17).
- Advanced parsers (Word, HTML upload) — deferred.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/ai_assistants/ingest.py` | **NEW** |
| `API/src/app/core/ai_assistants/file_upload.py` | **NEW** |
| `API/src/app/core/ai_assistants/tasks.py` | **NEW** |
| `API/src/app/core/ai_assistants/router.py` | **EDIT** — 5 new endpoints |
| `API/src/app/core/ai_assistants/service.py` | **EDIT** — knowledge service methods |
| `API/src/app/core/ai_assistants/data_access.py` | **EDIT** — knowledge + chunk queries |
| `API/src/app/shared/http/safe_fetch.py` | **NEW** — SSRF-defence fetcher |
| `API/pyproject.toml` | **EDIT** — add `pdfplumber`, `readability-lxml`, `filetype`, `httpx` |
| `API/src/app/main.py` | **EDIT** — register tasks module |
| `API/tests/ai_assistants/test_ingest_file.py` | **NEW** |
| `API/tests/ai_assistants/test_ingest_text.py` | **NEW** |
| `API/tests/ai_assistants/test_ingest_url_ssrf.py` | **NEW** |
| `API/tests/ai_assistants/test_dedup_and_replace.py` | **NEW** |
| `API/tests/ai_assistants/test_cancel_and_heartbeat.py` | **NEW** |
| `API/tests/shared/http/test_safe_fetch.py` | **NEW** |

**~15 files. ~800 lines.** Over — but ingest pipeline + 3 source types + SSRF fetcher + cancel/replace + dedup all interlock. Splitting would leave the UI (Step 11) hitting half-built endpoints.

## Plan

1. `safe_fetch.py` first — helper is small, testable, reusable.
2. `file_upload.py` next — pure validation, no DB.
3. `ingest.py` — synchronous-flow Celery task with async DB inside; use `async_to_sync` wrapper if Celery worker is sync.
4. Router endpoints — thin, delegate to service; service handles dedup + dispatch.
5. Replace flow: creates temp knowledge row with `assistant_id` = original's, ingests fully, on `status='ready'` deletes the original row (cascade removes original chunks) atomically.
6. Celery worker config: `--max-tasks-per-child=1` for the ingest queue (memory hygiene against parser leaks); ensure the deploy config picks this up.
7. PDF parser configured to disable JS + external URLs (`pdfplumber` doesn't run JS by default; verify no XRef URL fetching).

## DB changes / migrations

None — all tables exist from Step 5.

## Tests

- File upload: `.pdf` (valid) → ingest → chunks appear; `text-embedding-3-small` embeddings stored.
- File upload: `.exe` renamed `.pdf` → magic-byte sniff rejects with 422.
- File upload: zip-bomb PDF → decompression heuristic rejects.
- File upload: `filename="../../../etc/passwd"` → stored as `{knowledge_id}.bin`; `original_filename` = the original string (for display); no file appears outside org dir.
- File upload: `filename="CON.pdf"` on Windows → 422 rejected.
- Text ingest: 3000-char body → 4 chunks (with overlap).
- Same file uploaded twice → second call returns existing row's id, no double-ingest.
- URL ingest: `http://192.168.1.1/foo` → 422 with `private_ip_rejected`.
- URL ingest: `http://public.com` that 301s to `http://192.168.1.1` → 422 rejected on redirect.
- URL ingest: valid public URL → text extracted, chunks created.
- Cancel: while task is between chunks, `POST .../cancel` → task exits on next check, `status='failed_ingest'`, no chunks left.
- Heartbeat: during ingest, `heartbeat_at` updated at least every 30s (verified via time-mocked test).
- Replace: mid-replace, retrieval still returns v1 chunks; after replace completes, retrieval returns v2 chunks; never returns 0.
- Delete during ingest: row marked `pending_delete`; ingest checks on commit; no orphan chunks.

## Smoke

```
1. Create assistant with instructions "Answer from the docs".
2. POST /ai-assistants/{id}/knowledge/text {title:"FAQ", body_text:"Our office is at 123 Main St. We ship worldwide in 3-5 days."}
   → status='ready' after ~2s.
3. From preview: "Where is your office?" → assistant replies "Our office is at 123 Main St."
4. Try uploading a .exe — rejected. Upload a real PDF — ingests.
5. Try URL http://public-docs.com/faq — ingests. Try http://127.0.0.1 — rejected.
6. Upload same file twice — second returns existing id.
```

## Risks

- Celery async-in-sync worker setup varies; if the project's Celery config uses `--pool=solo` or `--pool=threads`, the async DB pattern differs. Plan phase inspects existing Celery config.
- `pdfplumber` is heavy; installation adds ~50MB to the image. Worth it in v1.
- `readability-lxml` is unmaintained but still functional; fine for v1.

## Self-check (10 rules)

`core/ai_assistants/` + new `shared/http/` helper. ✓ Rule 2: knowledge + chunks both org-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ Permission enforced. ✓ pack.yaml untouched. ✓ 15 files / ~800 lines — over but justified. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 10 — Knowledge Source backend — file + custom text + URL + Celery ingest
Files: 15
Verify: all 3 source types ingest; magic-byte + reserved-name + SSRF rejects work;
        dedup returns existing row; cancel + replace preserve query availability;
        heartbeat written every 30s.
Tests: ~15 pytest cases.
Awaiting "proceed".
```
