# Step 2 — Flatten `data_access/` folder → `data_access.py` (auth, campaigns, contacts, email_sequences)

**Goal:** Convert the four `data_access/` folders to single `data_access.py` files. Pure relocation; behaviour preserved.
**Status:** Pending
**Depends on:** Step 1.

---

## Scope

In-scope:
- `core/auth/data_access/` → `core/auth/data_access.py`
- `core/campaigns/data_access/` → `core/campaigns/data_access.py`
- `core/contacts/data_access/` → `core/contacts/data_access.py`
- `core/email_sequences/data_access/` → `core/email_sequences/data_access.py`

Out of scope:
- Adding new queries, renaming functions, behaviour changes.
- The other four folder-form DALs (Step 3).

## Files to touch

For each of the four modules:
- All sub-files inside `data_access/` (e.g. `auth/data_access/auth_sessions.py`, `campaigns/data_access/campaigns.py`, etc.) → concatenated into a single `data_access.py` next to `service.py`.
- The folder's `__init__.py` is deleted.
- The folder itself is removed.
- Callers that did `from src.app.core.<module> import data_access` continue to work unchanged (the import target is now a module file, not a package).
- Callers that did `from src.app.core.<module>.data_access import X` continue to work unchanged.
- Callers that imported a sub-file directly (e.g. `from src.app.core.users.data_access.users import X`) — grep first, rewrite to top-level import.

**~8 files modified (4 new `data_access.py` + 4 callers swept), ~9 files deleted (folders + sub-files), ~400 lines moved.**

## Plan

1. For each of the four modules:
   - Read all sub-files in `data_access/`.
   - Read `data_access/__init__.py` to confirm the public API.
   - Create `data_access.py` containing every function exported by the package. Preserve helper functions that were imported across sub-files (just include them in the new flat file).
   - Delete the `data_access/` folder.
2. Grep the entire backend tree for `from src.app.core.<module>.data_access.<subfile>` patterns and rewrite to `from src.app.core.<module>.data_access import ...`.
3. Run `uv run python -c "from src.app.core.<module> import service, router, data_access"` for each module.
4. Boot the app and smoke a read endpoint per module.

## DB changes / migrations

None.

## Tests

- Run existing module pytests if any (e.g. `tests/auth/`, `tests/campaigns/`, `tests/contacts/`).

## Smoke

- **auth:** login flow works end-to-end (login → 2FA → access protected endpoint).
- **campaigns:** open `/user/campaigns` → list loads.
- **contacts:** open `/user/contacts` → list loads.
- **email_sequences:** Settings → Email Sequences → list loads.

## Risks

- Cross-sub-file imports (e.g. `memberships.py` importing from `.users`) — flattening removes the boundary, so those calls become local function calls. Watch for name collisions across sub-files.
- `__init__.py` may have done re-exports under different names. Preserve the public surface exactly.

## Self-check (10 rules)

Pure relocation. All 10 rules unchanged. ✓ ~9 files / ~400 lines (right at the limit; split per-module if any single module exceeds it). Stop-and-report. ✓
