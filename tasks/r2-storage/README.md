# Track: Cloudflare R2 file storage

**Status:** Steps 0-8 COMPLETED 2026-09-29 - **local runs on R2** (`crm-local`). Step 9 (prod-neuradigi cutover) pending: runbook in `step-9-prod-neuradigi-cutover.md`. `prod` (aixo) deferred.
**Requested:** 2026-09-29 (manager instruction via user).
**Goal:** Every uploaded file lives in a Cloudflare R2 bucket instead of the server's `./storage` folder, so a server crash or rebuild never loses customer files. One separate Cloudflare account + bucket per environment.

This track **replaces a locked-stack rule**. CLAUDE.md currently says *"Local filesystem only … No S3/boto3 in this build."* The user approved the change on 2026-09-29, and Step 9 rewrites that line.

## Environments

| Environment (`API/.environment`) | Cloudflare account | Bucket | Secrets file | Step 0 |
|---|---|---|---|---|
| `local` | dev@karmcrm.com | `crm-local` | `secrets.local.enc.env` | ✅ 2026-09-29 |
| `prod-neuradigi` (neuradigi.com) | admin@karmcrm.com | `crm-prodneuradigi` | `secrets.prod-neuradigi.enc.env` | ✅ 2026-09-29 |
| `prod` (aixoapp.com) | aixoindia@gmail.com | TBD | `secrets.prod.enc.env` | ⏸ deferred by user |

Each secrets file carries four new keys: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_BUCKET`. Setup is in [`cloudflare-r2-setup-runbook.md`](cloudflare-r2-setup-runbook.md). Only one developer machine points at `crm-local`; other developers keep `STORAGE_BACKEND=local`. See the Cases section for why.

## Where we are today (audit 2026-09-29)

**The storage abstraction**
- `API/src/app/shared/storage/` has a synchronous `StorageBackend` ABC with one implementation, `LocalStorage`.
- `get_storage()` hard-codes `LocalStorage`. The `STORAGE_BACKEND` / `STORAGE_ROOT` keys in `config.env` are never read by it.
- `LocalStorage` does not store a content type.

**What uses it**
- About 15 call sites write through `get_storage()`:
  - catalog images
  - furniture inventory, field-visit and custom-order photos
  - real-estate property images
  - AI-assistant knowledge files and header profile pictures
  - call recordings
  - lead and contact import sources and reports

**Reads that bypass it and open `./storage` directly**
- contact imports `_read_file_bytes`
- the lead imports service and `parser.py`
- calls `read_recording_file`

**Mailgun inbound and quarantine**
- These use raw `open()` / `rename()` / `shutil`.
- Committed attachments live under `{org}/messages/{message_id}/`, are served by `FileResponse` in `conversations/router.py`, and carry a hard-coded `storage_backend: "local"`.
- Quarantine payloads (`tbl_email_quarantine.payload_path`) are kept for up to `EMAIL_QUARANTINE_AUTO_PURGE_DAYS` (default 30), and an operator can release them.
- Four modules each keep their own copy of the `STORAGE_ROOT` env lookup.

**The public `/files` mount**
- `main.py` mounts `/files` as a **public, unauthenticated `StaticFiles` over the whole `./storage` tree**.
- That exposes call recordings, import CSVs, email attachments and AI knowledge blobs to anyone holding the path.

**Other gaps**
- There is no boto3 dependency.
- `celery-beat` has no storage volume.
- `core/files/` exists as an empty package.

## Decisions

1. **One bucket per environment, each in its own Cloudflare account** (manager instruction). A leaked key cannot reach another environment's data, and local development can never overwrite production files. The overhead is separate billing and separate 2FA per account; the runbook records who owns each account.
2. **Buckets stay private.** There is no `r2.dev` URL and no public custom domain; only the API reads R2.
3. **The API streams files from R2; it does not redirect to presigned URLs.**
   - DB rows already store server-relative `/files/<key>` URLs. Keeping that shape means no change to any URL column and no frontend change. The Architect review confirmed that the only APP consumers of `/files` are image helpers.
   - Presigned URLs change on every request, which defeats browser caching.
   - Reads are streamed in chunks (`open_stream`), not loaded whole into memory.
   - This is an unsourced trade-off. Revisit a CDN-fronted public-assets bucket only if bandwidth becomes measurable.
4. **Public visibility comes from a registry, not hard-coded paths in core.**
   - Each module that serves no-login images declares its key patterns in `ModuleDescriptor.public_files`, the same descriptor that already carries its menu entry and permissions (rules 1, 5 and 6). `registry.public_file_patterns()` collects them; `shared/storage/public_patterns.py` parses and matches them:
     - catalog: `catalog/{org}/…`
     - furniture inventory, field_visits and custom_orders: `{org}/<entity>/…`
     - real-estate property: `{org}/property/…`
     - AI assistants: `{org}/ai_assistants/{assistant}/profile/…`
   - Patterns are matched **segment by segment**. Every `{org}` / `{id}` segment must parse as a UUID; there are no substring or regex-anywhere matches.
   - Anything not registered returns **404 at `/files`**. That covers call recordings, imports, `messages/`, quarantine and `ai_assistants/*.bin`, which stay reachable **only** through their existing authenticated, org-scoped endpoints.
   - The allowlist check runs **before** the ETag/304 check, so `If-None-Match` cannot probe private keys.
5. **Only raster images are served publicly.**
   - `/files` serves only `image/png`, `image/jpeg`, `image/webp` and `image/gif`. The type comes from the stored object metadata; on the local backend it is derived from the key's extension through the same helper.
   - SVG, HTML and anything else return 404, even under a registered prefix.
   - Responses send `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; sandbox`.
   - Upload paths under registered prefixes already sniff with libmagic (`shared/files/image.py`). Step 5 verifies each one and fixes any that stores the client-declared type.
   - Email attachments are always served with `Content-Disposition: attachment` (RFC 5987 filename) plus the same CSP and `nosniff`.
6. **Caching: `Cache-Control: no-cache` + `ETag`.**
   - Catalog (`{item_id}.{ext}`) and inventory (`cover.{ext}`) overwrite their keys in place, so a `max-age` would show stale images.
   - Revalidating is cheap because it returns a 304.
   - ETag source: the R2 object ETag, or size+mtime on local, hashed so it is opaque.
7. **`StorageBackend` becomes async** (`await storage.put(...)`).
   - Methods: `put`, `get`, `open_stream`, `stat` (size, etag, content_type), `delete`, `delete_directory`, `list_keys`.
   - `LocalStorage` wraps disk IO in `asyncio.to_thread`.
   - `R2Storage` uses **boto3 on a dedicated bounded thread pool** (not the default executor), so a slow R2 cannot starve other `to_thread` users.
   - boto3 is preferred to aioboto3 because aioboto3 pins botocore tightly (unsourced judgment).
   - boto3 config:
     - explicit connect and read timeouts
     - capped retries
     - `region_name="auto"` and SigV4
     - `request_checksum_calculation` / `response_checksum_validation` set to `when_required`, to avoid the newer botocore default CRC32 headers that R2 has rejected (from memory; verify against Cloudflare's boto3 docs in Step 3 and prove against the real bucket in Step 8)
8. **One shared key guard, in `shared/storage/keys.py`.**
   - It runs on the fully decoded key and rejects:
     - empty keys and keys with a leading `/`
     - `..` or `.` segments, backslashes and NUL
     - `//` and non-printable characters
   - Both backends and every `list_keys` result pass through it, including keys read back from R2 during `--reverse`.
   - **Prefix operations** (`delete_directory`, `list_keys`) refuse an empty prefix, require the first segment to be a UUID (or `catalog/<uuid>`), always append `/`, and cap each call at 10,000 objects.
   - Reads of keys taken from DB rows go through `get_for_org(org_id, key)`, which asserts the key starts with `{org_id}/` or `catalog/{org_id}/`.
9. **Backend is chosen by `STORAGE_BACKEND`** (`local` | `r2`).
   - `config.env` keeps `local`, and each `config.<env>.env` sets `r2` at cutover.
   - The **test suite always forces `local`**, so pytest never touches a real bucket.
   - If `STORAGE_BACKEND=r2` and any `R2_*` variable is missing, startup fails and **names the missing variables** (never their values).
   - R2 being unreachable at startup is **logged, not fatal**. An R2 blip must not take down login, leads and the rest of the CRM; the request-time 503/502 handling covers it.
   - `STORAGE_ROOT` is read through one shared helper that the Mailgun temp-path code also uses, replacing its four copies.
10. **Mailgun data:**
    - `pending-inbound/`, `pending-events/` and `{org}/staging/` stay on local disk. They are short-lived and pass between request and task.
    - **Committed attachments** (`{org}/messages/{message_id}/…`) move to storage.
    - **Quarantine payloads** also move to storage (`{org}/quarantine/{id}/…`), because they are held for weeks and can be released.
    - Read paths use the **active backend**, not the per-row `storage_backend` field. That field is informational, so migration and rollback never desync it.
11. **Existing files are copied, not moved**, with `run storage-migrate`.
    - Same keys; temp prefixes are skipped; symlinks are never followed; each object's content type is set from its extension (`mimetypes`).
    - **Pre-flip pass:** copies when the object is absent, or differs in size or MD5.
    - **Post-flip pass** (`--only-missing`): copies only absent keys, so it never overwrites a file uploaded to R2 after the flip.
    - `--dry-run` and `--reverse` (bucket → disk, key guard enforced; used for rollback) are supported.
    - A lock file prevents two concurrent runs.
    - `./storage` stays as a second copy for 30 days. Step 9 records the removal date and owner.
12. **Competitor benchmark** (unsourced; no `PRODUCT_BRIEF.md` exists):
    - HubSpot, Zoho, Pipedrive and Salesforce store files in object storage. They serve private files through authenticated URLs or short-lived signed links, and public assets through a CDN.
    - Private files: our design matches.
    - Deliberate differences:
      - public images are proxied through the API rather than a CDN (Decision 3)
      - visibility comes from a prefix registry rather than a per-file visibility property on a files table (see Follow-ups)

## Steps

| # | Step | Layer | Depends on |
|---|---|---|---|
| 0 | **Cloudflare setup (user).** Account, private bucket and bucket-scoped *Object Read & Write* token per environment; the default multipart-abort lifecycle rule is confirmed present; values added with `run secrets-edit`. | ops | — |
| 1 | **Async storage interface + key guard.** Make `StorageBackend` async, add `open_stream` / `stat` / `list_keys` to it, and add the `keys.py` guard. Convert `LocalStorage`, add `await` at every call site, update tests. This is mechanical and exceeds the 10-file guideline because a half-converted interface is not runnable. | shared + all callers | — |
| 2 | **Route bypassing reads through storage.** Contact imports, lead imports service + `parser.py`, and call recordings move to `get_for_org(...)`. `Path("./storage")` is removed from `core/`. Call-recording download streams through `open_stream`. | core | 1 |
| 3 | **`R2Storage` + backend selection.** Add `shared/storage/r2.py` and read `STORAGE_BACKEND` in `get_storage()`. Also: config validation, a shared `STORAGE_ROOT` helper, boto3 in `requirements.txt`, `R2_*` in the `docker-compose.yml` secret passthrough, and the `storage` volume on `celery-beat`. | shared | 1 |
| 4 | **Public-file patterns.** `ModuleDescriptor.public_files` + `shared/storage/public_patterns.py`; each owning module (catalog, furniture ×3, real_estate property, ai_assistants) declares its pattern in `module.py`. | shared + modules | 1 |
| 5 | **`/files/{key}` router replaces the static mount.** Fill the existing `core/files/` (router → service; no DAL, since there is no DB). Behaviour follows Decisions 4–6, with a per-IP rate limit reusing the existing limiter. Verify that every registered-prefix upload path sniffs its type. | core/files | 1, 3, 4 |
| 6 | **Mailgun committed attachments → storage.** `commit_attachments` uploads from staging, then deletes the staging copy. The conversations endpoint streams with `Content-Disposition: attachment`. `orphan_cleanup`'s `{org}/messages` scan uses `list_keys`. | core/email, core/conversations | 1, 3 |
| 7 | **Quarantine payloads → storage.** When quarantining, copy the payload to `{org}/quarantine/{id}/` and store that key. Release, purge and preview read and delete through storage. | core/email | 6 |
| 8 | **`run storage-migrate`** (Decision 11), plus **local cutover and smoke** against Ajay's Workspace: set `STORAGE_BACKEND=r2` in `config.local.env`, then migrate → flip → `--only-missing`, then smoke every upload type. | shared + ops | 0, 2–7 |
| 9 | **prod-neuradigi cutover + CLAUDE.md.** Migrate → flip → restart **every** api/celery/beat container → `--only-missing` → smoke. Rewrite the CLAUDE.md file-storage locked-stack line. Record the `./storage` removal date. `prod` (aixo) repeats this step later, when the user schedules it. | ops + docs | 8 |

## Cases

- **A DB commit fails after an upload to R2 succeeded.** An orphaned object is left behind. Uploads always happen before the commit, so there is never a DB row pointing at nothing; Step 1 checks this at every call site. The property-images path already deletes on rollback. Other orphans are negligible in cost and are covered by the follow-up files registry.
- **R2 is unreachable during an upload.** The endpoint returns 503 "File storage temporarily unavailable" and no DB row is written.
- **R2 is unreachable during a read.** `/files` returns 502. Authenticated downloads return 503.
- **Two API workers and Celery run at once.** All processes see the same bucket. Today `celery-beat` sees no storage at all, so this is an improvement.
- **User A uploads during the cutover.**
  - Before the flip, the file goes to disk and the `--only-missing` pass picks it up.
  - After the flip, it goes straight to R2.
  - Every container is restarted before the catch-up pass, so no stale worker keeps writing to disk.
- **User B replaces a file after the flip.** R2 holds the newer copy, and the catch-up pass only copies keys that are absent, so it never overwrites it.
- **`storage-migrate` runs twice, is interrupted, or two operators start it together.** The command is idempotent and resumes where it stopped. A lock file refuses a concurrent run.
- **We roll back to local.**
  1. Run `--reverse`.
  2. Flip `STORAGE_BACKEND=local`.
  3. Restart every container.
  4. Run `--reverse --only-missing`.
  5. The key guard stops a malicious key in the bucket from writing outside `./storage`.
- **Two developers use the `crm-local` bucket.** Seeded or restored databases share org and row UUIDs, so their keys would collide, and one developer's deletes and orphan sweeps would remove the other's files. That is why only one machine points at `crm-local`, as recorded in the runbook.
- **Someone requests a private key at `/files/…`, a crafted traversal key, or an SVG or HTML file under a public prefix.** All three return 404.
- **Someone floods `/files` with random keys.** A per-IP rate limit applies, and the bounded storage thread pool protects the rest of the API.
- **An email attachment has a hostile filename or content.** Filenames are already sanitised on arrival (`_sanitize_attachment_filename`), and attachments are always served as a download under the sandbox CSP.
- **A row carries a key from another org.** `get_for_org` returns 404.
- **An R2 token leaks.** Only that environment's bucket is exposed. Rotate the token in Cloudflare, then run `run secrets-edit`.
- **Pending Mailgun data is lost in a crash between the webhook's 200 and the ingest task.** Mailgun will not retry that delivery. The window is seconds, and this is accepted; the pending-inbound sweeper already handles abandoned payloads.

## Tests

- **Step 1**
  - Every existing storage-touching test passes against the async interface.
  - `list_keys` returns only keys under the prefix.
  - The key guard rejects `../x`, `/x`, `a//b`, `a\b`, `a/./b`, `%2e%2e/x` (decoded) and NUL.
  - `delete_directory("")` and `delete_directory("not-a-uuid/x")` raise.
- **Step 2**
  - Lead and contact imports still parse from a source written through storage.
  - A call-recording download streams back the uploaded bytes.
  - A recording row carrying another org's key returns 404.
  - A pin-test asserts there is no `Path("./storage")` under `src/app/core/`.
- **Step 3**
  - The `R2Storage` round trip (put / get / open_stream / stat / delete / delete_directory / list_keys) passes against a moto S3 stub.
  - `delete_directory` batches correctly when more than 1,000 keys match.
  - `STORAGE_BACKEND=r2` with `R2_BUCKET` missing raises, naming `R2_BUCKET` and no value.
  - An unreachable endpoint at startup logs a warning and does not raise.
- **Step 4**
  - Registered patterns match only UUID segments.
  - `{org}/ai_assistants/<id>.bin` does not match the profile pattern.
  - A key containing "profile" elsewhere does not match.
- **Step 5**
  - A registered PNG returns 200 with `image/png`, `nosniff`, the CSP header and an ETag.
  - Sending `If-None-Match` returns 304.
  - A private key returns 404, both with and without `If-None-Match`.
  - An SVG under a public prefix returns 404.
  - A traversal key returns 404.
  - The static mount is gone.
- **Step 6**
  - An inbound attachment ends up under `{org}/messages/{id}/`, and its staging copy is removed.
  - The endpoint returns it with `Content-Disposition: attachment` for the owning org, and 404 for another org.
- **Step 7**
  - A quarantined message's payload is readable from storage after the local pending directory is deleted.
  - Release still works.
  - Purge deletes the stored payload.
- **Step 8**
  - `--dry-run` copies nothing.
  - A real run copies disk to the stub bucket with the right content types.
  - `--only-missing` never overwrites an object that differs.
  - Temp prefixes and symlinks are never copied.
  - `--reverse` restores to disk and rejects a planted `../` key.
  - A second concurrent run is refused.
  - The manual smoke on local covers every upload type, one public store page and one chat-widget avatar.
- **Step 9**
  - Manual smoke on neuradigi using the same checklist.

## Follow-ups (recorded so they aren't mistaken for oversights)

- **Login-gated internal photos.** Field-visit, custom-order and inventory photos are viewable by link today. Gating them needs signed URLs plus frontend changes; that is a separate track.
- **A files registry table** (size, type, owner, visibility per file). It would enable per-org purge, orphan detection and storage quotas, which HubSpot, Zoho and Pipedrive all have (unsourced).
- **Deleting files when their parent record is deleted** (catalog item, property, lead or contact merge, conversation), and a **full per-org purge** on org deletion. Both are gaps today, not regressions.
- **Protection against deliberate deletion by a token holder.** R2's Bucket Lock retention rules are the candidate. Confirm first whether R2 offers S3-style object versioning; the earlier claim that it does was removed as unverified.
- Byte-range (seek) support for call-recording playback.
- Rotating and offboarding the shared `crm-local` token.
- Legacy `API/src/providers/file_provider.py` is dead template code and is untouched.
