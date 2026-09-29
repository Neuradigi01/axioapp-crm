# Track: Cloudflare R2 file storage

**Status:** Plan — awaiting approval. No step files yet.
**Requested:** 2026-09-29 (manager instruction via user).
**Goal:** Every uploaded file lives in a Cloudflare R2 bucket instead of the server's `./storage` folder, so a server crash or rebuild never loses customer files. One separate Cloudflare account + bucket per environment.

This track **replaces a locked-stack rule**. CLAUDE.md currently says *"Local filesystem only … No S3/boto3 in this build."* The user approved the change on 2026-09-29; Step 8 rewrites that line.

## Environments

| Environment (`API/.environment`) | Cloudflare account | Bucket | Secrets file |
|---|---|---|---|
| `local` | dev@karmcrm.com | `crm-local` | `secrets.local.enc.env` |
| `prod` (aixoapp.com) | aixoindia@gmail.com | `crm-prod` | `secrets.prod.enc.env` |
| `prod-neuradigi` (neuradigi.com) | admin@karmcrm.com | `crm-neuradigi` | `secrets.prod-neuradigi.enc.env` |

New secret keys (each env file): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. Setup instructions: `cloudflare-r2-setup-runbook.md` (written with Step 0).

## Where we are today (audit 2026-09-29)

- `API/src/app/shared/storage/` has a `StorageBackend` ABC with one implementation, `LocalStorage`. `get_storage()` hard-codes it; `STORAGE_BACKEND` / `STORAGE_ROOT` in `config.env` are never read by it.
- The interface is **synchronous**. Fine for local disk; an R2 call made synchronously inside an `async def` blocks the event loop for the whole network round-trip.
- ~15 call sites write through `get_storage()`: catalog images, furniture inventory / field-visit / custom-order photos, real-estate property images, AI-assistant knowledge files + header profile pictures, call recordings, lead + contact import sources and reports.
- **Reads that bypass the interface** and open `./storage` directly: contact imports `_read_file_bytes`, lead imports service (source + 3 reports) and `parser.py`, calls `read_recording_file`.
- **Mailgun inbound** writes attachments with raw `open()/rename()/shutil`, keys them under `{org}/messages/{message_id}/`, serves them via `FileResponse` in `conversations/router.py`, and hard-codes `storage_backend: "local"` in `tbl_messages.attachments`.
- `main.py` mounts `/files` as a **public, unauthenticated `StaticFiles` over the entire `./storage` tree**. That exposes call recordings, import CSVs, email attachments and AI knowledge blobs to anyone holding the path.
- No boto3 dependency. `celery-beat` has no storage volume.

## Decisions

1. **One bucket per environment, in three separate Cloudflare accounts.** Manager instruction. A leaked prod key cannot touch another env's data, and local development can never overwrite prod files.
2. **Bucket stays private. No `r2.dev` or custom public domain.** The API is the only thing that reads R2.
3. **Serving model: the API streams files from R2; it does not redirect to presigned URLs.**
   - DB rows already store server-relative `/files/<key>` URLs. Keeping that URL shape means **no data migration of any URL column and no frontend change**.
   - A presigned URL changes on every request, which defeats browser caching of images. Streaming lets us send stable `ETag` / `Cache-Control`.
   - Cost: image bytes pass through the API. The images are small (upload caps already enforced by `shared/files/image.py`), so this is acceptable. Unsourced trade-off; revisit with a CDN-fronted public-assets bucket only if bandwidth becomes measurable.
4. **`/files/{key}` serves only image assets; everything else is 404 there.** `<img>` tags on the public store / listings / property pages and the chat widget cannot send a JWT. So images must remain link-accessible, exactly as today. The allowlist is by key shape:
   - `catalog/{org}/…`
   - `{org}/inventory/…`
   - `{org}/field_visits/…`
   - `{org}/custom_orders/…`
   - `{org}/property/…`
   - `{org}/ai_assistants/{assistant}/profile/…`

   Everything else is private. That covers call recordings, imports, `messages/` attachments and `ai_assistants/*.bin` knowledge files, which are **only** reachable through their existing authenticated, org-scoped endpoints. This closes the current `/files` leak.
5. **`StorageBackend` becomes async** (`await storage.put(...)`). `LocalStorage` wraps disk IO in `asyncio.to_thread`. `R2Storage` uses **boto3 + `asyncio.to_thread`**, not `aioboto3`. boto3 clients are thread-safe, and aioboto3 pins aiobotocore/botocore versions tightly, which is a recurring dependency-conflict source. Unsourced judgment.
6. **Backend chosen by `STORAGE_BACKEND`** (`local` | `r2`).
   - `config.env` keeps `local` as the default.
   - Each `config.<env>.env` sets `r2` at cutover time.
   - The **test suite always forces `local`** (conftest), so pytest never touches a real bucket.
   - With `r2` selected, missing `R2_*` variables make the API fail at startup with a clear error. There is no silent fallback to disk.
7. **Mailgun temporary data stays on local disk.** That covers `pending-inbound/`, `pending-events/`, `{org}/staging/` and `tbl_email_quarantine.payload_path`. These live for seconds to minutes, and Mailgun retries delivery on failure. Only **committed** attachments (`{org}/messages/{message_id}/…`) move to R2, keeping the same key layout.
8. **Existing files are copied, not moved.** A one-off command, `run storage-migrate`, copies `./storage/**` to the bucket under identical keys and skips Mailgun temp folders.
   - It is idempotent: an object is skipped when it already exists with the same size.
   - It supports `--dry-run`.
   - `--reverse` (bucket → disk) is the rollback path.
   - `./storage` stays on disk for 30 days after cutover as a second safety copy.
9. **Key layout is unchanged.** Every current key already starts with the org id (or `catalog/{org}`), so per-org prefix deletes keep working on R2.
10. **Competitor benchmark (unsourced; no `PRODUCT_BRIEF.md` exists):** HubSpot, Zoho and Pipedrive all store attachments in object storage and serve private files through authenticated app URLs or short-lived signed links, and public marketing images via CDN. Our model matches this for private files. Deliberate difference: public images are proxied through the API rather than a CDN (Decision 3).

## Steps

| # | Step | Layer | Depends on |
|---|---|---|---|
| 0 | **Cloudflare setup (user).** Three accounts, one private bucket each, one bucket-scoped *Object Read & Write* API token each, values added via `run secrets-edit`. Runbook `cloudflare-r2-setup-runbook.md`. | ops | — |
| 1 | **Async storage interface.** `StorageBackend` methods become `async`, and a `list_keys(prefix)` method is added for the migration and orphan sweeps. `LocalStorage` uses `to_thread`. Every call site gets `await` (mechanical; exceeds the 10-file guideline because a half-converted interface is not runnable). Tests updated. | shared + all callers | — |
| 2 | **Route bypassing reads through storage.** Contact imports `_read_file_bytes`, lead imports service + `parser.py`, and calls `read_recording_file` switch to `await get_storage().get(key)`. `Path("./storage")` is removed from `core/`. | core | 1 |
| 3 | **`R2Storage` backend + selection.** `shared/storage/r2.py` provides `put` (with `ContentType`), `get`, `delete`, `delete_directory` (list + `delete_objects` in batches of 1000), `list_keys` and `head`. `get_storage()` reads `STORAGE_BACKEND`. Also: key-traversal guard, a startup `head_bucket` check, boto3 added to `requirements.txt`, `R2_*` added to the `docker-compose.yml` secret passthrough, `storage` volume added to `celery-beat`. | shared | 1 |
| 4 | **`/files/{key}` router replaces the static mount.** New `core/files/` (router → service; no DAL, since no DB) enforces the Decision 4 allowlist. It streams via `get_storage()` with the stored `Content-Type`, `X-Content-Type-Options: nosniff`, `ETag`, `Cache-Control: public, max-age=3600`, and 304 on `If-None-Match`. The `StaticFiles` mount at `/files` is removed. | core/files | 1, 3 |
| 5 | **Mailgun committed attachments → storage.** `commit_attachments` uploads from local staging via `storage.put` and then deletes the staging copy. The conversations attachment endpoint reads through `storage.get`. `storage_backend` in `tbl_messages.attachments` records the active backend name. `orphan_cleanup`'s `{org}/messages` scan uses `list_keys`. | core/email, core/conversations | 1, 3 |
| 6 | **`run storage-migrate` command.** A CLI module under `shared/storage/`, wired into `run.cmd` / `run.sh`. It supports `--dry-run` and `--reverse`, excludes the temp prefixes, and prints copied / skipped / failed counts and total bytes. | shared + ops | 3 |
| 7 | **Local cutover + smoke** (Ajay's Workspace). Set `STORAGE_BACKEND=r2` in `config.local.env`, run `storage-migrate`, and smoke every upload type. | ops | 0, 2–6 |
| 8 | **Prod cutovers + CLAUDE.md.** Sequence for `prod`, then `prod-neuradigi`: migrate → flip → deploy → migrate again (catches files written between runs) → smoke. Then rewrite the CLAUDE.md "File storage" locked-stack line and this track's status. | ops + docs | 7 |

## Cases

- **Upload to R2 succeeds, then the DB commit fails.** An orphan object remains. The property-images path already deletes on rollback; other paths behave as today on disk. The cost is negligible, and no dangling DB row is ever created because upload precedes commit.
- **R2 unreachable during upload.** The service raises and the endpoint returns 503 "File storage temporarily unavailable". No DB row is written.
- **R2 unreachable during `/files` read.** Returns 502; the UI shows a broken image. No retry storm, because the browser does not auto-retry `<img>`.
- **Two API workers + Celery.** Today they share the host disk (and `celery-beat` has no volume). On R2 all processes see the same bucket, so there is no regression.
- **User A uploads while `storage-migrate` runs.** With the flip not yet done, the file lands on disk and the second migrate pass picks it up. With the flip already done, it lands in R2 directly. The second pass guarantees nothing written before the flip is missed.
- **`storage-migrate` run twice or interrupted.** Idempotent: existing same-size objects are skipped, so a re-run resumes.
- **Rollback to local after the flip.** `run storage-migrate --reverse`, then set `STORAGE_BACKEND=local`. Files uploaded to R2 after the flip come back to disk.
- **Org deleted.** Behaviour is unchanged: the tenants cleanup task deletes only the `{org}/ai_assistants` prefix, now via R2 `delete_directory`. Full per-org blob purge is a pre-existing gap, **out of scope**, and recorded here so it is not forgotten.
- **Several developers share the `crm-local` bucket.** Keys start with org/row UUIDs, so they do not collide. `storage-migrate` from one laptop does not overwrite another's objects because keys differ.
- **Guessing a private key at `/files/…`** (e.g. `{org}/call_recordings/{uuid}.mp3`). Returns 404 because the key is not in the allowlist, even if it exists.
- **Crafted key** (`../`, absolute path, URL-encoded traversal). Rejected by the shared key guard before any backend call, on both backends.
- **R2 token leaks.** It is scoped to one bucket in one account; other environments are unaffected. Rotate the token in Cloudflare, then `run secrets-edit`.

## Tests

- Step 1: every existing storage-touching test passes with the async interface; `LocalStorage.list_keys` returns only keys under the prefix.
- Step 2: a lead import and a contact import still parse after their source is written through `get_storage()`; call-recording download returns the uploaded bytes; a grep pin-test asserts no `Path("./storage")` remains under `src/app/core/`.
- Step 3: an `R2Storage` test against a moto S3 stub covers put/get/delete/delete_directory/list_keys round-trip; `delete_directory` with >1000 keys batches correctly; `../etc/passwd` is rejected; `STORAGE_BACKEND=r2` with a missing `R2_BUCKET` raises at startup.
- Step 4: an allowlisted image key returns 200 with the stored content type, `nosniff` and an `ETag`; a repeat with `If-None-Match` returns 304; a call-recording key, an import key, a `messages/` key and an `ai_assistants/<id>.bin` key each return 404; a traversal key returns 404; the old static mount is gone.
- Step 5: a Mailgun inbound attachment ends up readable via `storage.get` under `{org}/messages/{id}/…`; the staging copy is deleted; the conversations attachment endpoint returns it for the owning org and 404 for another org.
- Step 6: dry-run copies nothing and reports counts; a real run copies disk → stub bucket; a second run skips everything; temp prefixes are never copied; `--reverse` restores to disk.
- Steps 7–8: manual smoke checklist in each step file, covering every upload type in the table above plus one public-store page and one chat-widget avatar.

## What this track does NOT do

- CDN / public custom domain for images (Decision 3 revisit condition).
- Moving Mailgun temp data or quarantine payloads to R2 (Decision 7).
- Full per-org blob purge on org deletion (pre-existing gap).
- Legacy `API/src/providers/file_provider.py` (dead template code, unused).
- R2 bucket versioning or object-lock policies. Can be enabled from the Cloudflare dashboard later without code changes.
