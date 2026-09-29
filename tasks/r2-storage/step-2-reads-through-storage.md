# Step 2: Route bypassing reads through storage

**Status:** COMPLETED (2026-09-29)
**Depends on:** Step 1
**Blocks:** Step 8 (a cutover is only safe once no reader touches `./storage` directly)

## Goal

Every read of a stored import file or call recording goes through `get_storage()` and is scoped to the row's org. Nothing under `core/` opens `./storage` on disk directly.

## Scope

- `core/leads/imports/parser.py`: `parse_rows(storage_path, data, mapping)` now takes bytes. `_open_file_bytes` is removed.
- `core/leads/imports/service.py`:
  - New `_read_stored(import_row, key, detail)` reads via `get_storage().get(assert_org_key(...))` and answers 404 when the file is missing or belongs to another org.
  - `read_source_file`, `read_error_csv`, `read_skipped_csv`, `read_warnings_csv` and `read_preview` are now async and use it.
- `core/leads/imports/tasks.py`: the processor reads the source through storage before parsing.
- `core/leads/imports/router.py`: adds `await` to the five reader calls.
- `core/contacts/imports/service.py`: `_read_file_bytes(row)` is async, reads through storage and is org-scoped. It has 3 callers.
- `core/calls/service.py`: `read_recording_file` returns `(chunks, content_type, size)`.
  - A stored key belonging to another org returns 404.
  - A missing file returns 410. This is checked with `stat` before any bytes are streamed.
- `core/calls/router.py`: the recording endpoint streams through `StreamingResponse` with `Content-Length`.

## Test

`tests/shared/test_storage_reads.py`:
- A pin-test finds no `Path("./storage")` anywhere under `core/` or `packs/`.
- `parse_rows` parses CSV bytes.
- The lead error report reads through storage; a key from another org returns 404.
- The contact import source reads through storage; a key from another org returns 404.
- A recording streams its full bytes as `audio/mpeg` with the right size; a key from another org returns 404; a missing file returns 410.
