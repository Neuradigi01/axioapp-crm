# Step 6 — `log_entity_change` audit wrapper

**Goal:** Replace 126 inlined `audit.log("entity.created/updated/deleted", entity_type=..., entity_id=..., after=_snapshot(...))` calls with one shared wrapper.
**Track:** Code Update — Audit & Validation
**Depends on:** none (Step 7 builds the snapshot side)
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/audit/helpers.py::log_entity_change(audit, *, action, entity_type, entity_id, before=None, after=None, actor=None)`.
- Wrapper formats the event name as `{entity_type}.{action}` and forwards to the existing audit service.
- Migrate the 126 known call sites across `app/core/` and `app/packs/furniture/`.

**Out of scope:**
- Audit storage layer (untouched).
- Auto-snapshot logic (Step 7).

## Files to touch
- `api/src/app/shared/audit/__init__.py` (create)
- `api/src/app/shared/audit/helpers.py` (create)
- Every `service.py` that currently calls `audit.log(...)` in create/update/delete paths (`contacts`, `leads`, `appointments`, `tasks`, `walk_ins`, `catalog`, `campaigns`, `calls`, `conversations`, `reviews`, `billing`, plus pack modules).
- `api/tests/shared/test_audit_wrapper.py` (create)

## Plan
1. Implement wrapper — thin pass-through that derives event name + ensures `before/after` dicts are JSON-serializable.
2. Grep `await audit\.log\(` → ~126 hits.
3. Replace each. Wrapper signature is keyword-only so swap is unambiguous.
4. Confirm audit-event store still contains identical event shape after migration (run one create → check DB row).

## DB changes / migrations
None.

## Tests to add
- Unit: wrapper formats event name correctly (`contact.created`).
- Unit: wrapper rejects unknown action (allow-list: `created / updated / deleted`).
- Integration: create one contact, assert audit row is identical to pre-refactor shape.

## Verification checklist
- `uv run pytest` — green.
- Browser smoke: create a contact, open audit log, see `contact.created` entry with correct snapshot.

## Self-check (10 rules)
- [ ] Event-name format unchanged (avoid silently breaking dashboards/queries).
- [ ] Old inlined `audit.log` calls deleted (not commented).

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
