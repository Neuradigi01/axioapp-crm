# Step 1: Async storage interface + key guard

**Status:** Pending
**Depends on:** none
**Blocks:** Steps 2–9

## Goal

Make `StorageBackend` async and give it the full method set that R2 needs, add one shared key guard, and convert every caller. Behaviour stays identical: files are still written to `./storage` on local disk.

## Scope

**`API/src/app/shared/storage/`**

- `base.py`: every method becomes `async`.
  - `put(key, data, content_type=None) -> StoredFileRef`
  - `get(key) -> bytes`
  - `open_stream(key, chunk_size=64 KiB) -> AsyncIterator[bytes]`
  - `stat(key) -> StoredFileStat(size, etag, content_type)`, which raises `FileNotFoundError`
  - `delete(key) -> bool`
  - `delete_directory(prefix) -> int`
  - `list_keys(prefix) -> AsyncIterator[str]`
  - `url(key) -> str` stays sync; it is pure string work.
- `keys.py` (new):
  - `validate_key(key) -> str` rejects:
    - empty keys and keys with a leading `/`
    - `.` and `..` segments
    - `//`, backslash and NUL
    - control characters
  - `validate_prefix(prefix) -> str` applies the same rules. It also requires the first segment to be a UUID, or the prefix to be `catalog/<uuid>`, and it always appends `/`.
  - `content_type_for(key)` guesses the type from the extension using `mimetypes`.
  - `assert_org_key(org_id, key)` checks the key starts with `{org}/` or `catalog/{org}/` and raises `FileNotFoundError` otherwise, so callers can 404.
- `local.py`:
  - Disk IO runs through `asyncio.to_thread`.
  - `_resolve_safe` calls `validate_key` first.
  - `stat` returns size, an opaque ETag (a hash of size and mtime) and `content_type_for`.
  - `delete_directory` and `list_keys` use `validate_prefix` and cap at 10,000 objects.
- `__init__.py` exports the new names. `get_storage()` still returns `LocalStorage`; Step 3 changes that.

**Callers:** add `await` to every call. The async functions already exist, so no caller signature changes.

- `core/catalog/service.py`
- `core/ai_assistants/service.py`
- `core/ai_assistants/ingest.py`
- `core/calls/service.py`
- `core/contacts/imports/service.py`
- `core/leads/imports/service.py`
- `core/leads/imports/tasks.py`
- `core/tenants/tasks.py`
- `packs/furniture/modules/{inventory,field_ops,custom_orders}/service.py`
- `packs/real_estate/modules/property/service.py`

The step also confirms at every call site that the upload happens **before** `db.commit()`. Any site that does it the other way round is reported, not silently reordered.

**Tests:** the roughly 6 test files that patch `get_storage` / `LocalStorage` switch to async fakes. New file `tests/shared/test_storage_keys.py`.

**File count:** about 20 files. This exceeds the 10-file guideline on purpose. The change is a mechanical `await` insertion, and a half-converted interface would not run.

## Checklist

- [ ] No sync `get_storage().<method>(` call is left under `src/app/`. Grep proves it.
- [ ] `validate_key` rejects `../x`, `/x`, `a//b`, `a\b`, `a/./b` and `a\x00b`.
- [ ] `delete_directory("")` and `delete_directory("not-a-uuid/x")` raise `ValueError`.
- [ ] `list_keys("<uuid>/imports")` does not return keys under `<uuid>/imports_old/`.
- [ ] `stat` returns the right size, a stable ETag and `image/png` for a `.png` key.
- [ ] Existing storage tests pass. Ask before running pytest (it takes about 12 minutes).
- [ ] `ruff format` + `ruff check` are clean.
- [ ] The layered-architecture and table-name pin-tests still pass.

## Test

- `tests/shared/test_storage_keys.py`:
  - the guard cases
  - the prefix cases
  - `LocalStorage` round trip: put, stat, get, open_stream, list_keys, delete, delete_directory
- Existing catalog, property, AI assistant, import and call tests pass unchanged apart from the async fakes.
