# Step 5: `/files/{key}` router replaces the static mount

**Status:** COMPLETED (2026-09-29)
**Depends on:** Steps 1, 3, 4

## Goal

`/files/…` stops serving the whole `./storage` folder to anyone. It serves only images that a module declared public, and returns 404 for everything else.

## Scope

- **`core/files/service.py`: `open_public_file(key, if_none_match)`** runs these checks in order:
  1. The key must match a declared public pattern (`registry.public_file_patterns()`).
  2. Storage `stat` is called.
  3. The stored type must be `image/jpeg`, `image/png` or `image/webp`.
  4. The ETag is compared, returning 304 on a match. This runs only after the allowlist check, so `If-None-Match` cannot probe a private key.
  - A missing or bad key returns 404. A storage failure returns 502.
- **`core/files/router.py`: `GET /files/{key:path}`**, mounted at the app root:
  - Per-IP rate limit of 600 requests per minute (`InMemoryRateLimiter` + `parse_client_ip` with `TRUSTED_PROXIES`).
  - Headers: `nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, `Cache-Control: no-cache`, `ETag`.
  - The file is streamed with `Content-Length`.
- **`main.py`:** the `StaticFiles` mount at `/files` is removed and `files_router` is included.
- **Upload sniffing fixed.** Furniture field-visit photos (admin and staff portal), custom-order photos and the inventory cover used to store the client-declared Content-Type and the extension from the filename. They now use the new `shared/files/image.require_image_upload` (libmagic, 422 on a non-image). Photos have a 10 MB cap (`PHOTO_MAX_BYTES`), and the cover keeps 5 MB. The `content_type` / `file_extension` / `filename` parameters were removed from those services and routers.

## Test

`tests/test_files_public.py`, 7 tests:
- A PNG returns 200 with every security header, and a repeat with `If-None-Match` returns 304.
- Existing private keys return 404, with and without `If-None-Match: *`.
- SVG, HTML and PDF files under a public prefix return 404.
- Missing keys and encoded traversal keys return 404.
- The rate limit returns 429.
- `require_image_upload` rejects HTML.
- The three furniture uploads reject HTML disguised as an image with 422.

Live check on local: a real catalog image returns 200; a real import CSV that used to be publicly downloadable now returns 404.
