# Step 6 — `core/public_ingest/custom_events/` CRUD + validation + reserved-name check + Owner-only edits

**Goal:** ship the definitions module (Router → Service → DAL) with NFKC+ASCII validation, reserved-name checks, `add_prefix()` publish helper, single audit-history via `core/audit/`, Owner-only edit/delete/reactivate.
**Phase:** Custom Events track — step 6/17
**Depends on:** Step 5
**Status:** Pending

## Scope

**In-scope:**
- Endpoints under `/api/v1/custom-events`:
  - `GET /` (Admin+) — list org's events.
  - `GET /{id}` (Admin+) — event detail.
  - `POST /` (Admin+) — create.
  - `PUT /{id}` (Owner-only) — edit (label, category, payload_schema).
  - `DELETE /{id}` (Owner-only) — soft-delete (`is_active=false`).
  - `POST /{id}/reactivate` (Owner-only).
- Validation on create/edit:
  - `name`: NFKC normalize + regex `^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){0,3}$` (ASCII-only; rejects Unicode homoglyphs).
  - Reserved-name check: after normalization, `custom.<name>` must not collide with any string in `core/events/event_catalog.ALL_EVENTS`. Combined with Track A's Step 5 approach.
  - `payload_schema`: validated per per-property spec (types + max_length + enum caps per README).
- `core/public_ingest/custom_events/utils.py`:
  - `add_prefix(name: str) -> str` — returns `f"custom.{name}"`.
  - `strip_prefix(qualified_name: str) -> str` — for reverse display.
  - Both used everywhere; never inline string manipulation.
- Optimistic lock on edit: `PUT` requires `If-Match: <updated_at_iso>` header; 409 on mismatch.
- Every mutation emits audit event via `core/audit/`: `custom_event.created`, `custom_event.schema.edited` (with before/after JSON diff), `custom_event.soft_deleted`, `custom_event.reactivated`. This is the ONLY schema-history source — no separate version table (per architect finding).
- Permission registration: `custom_events.view` (Admin+), `custom_events.create` (Admin+), `custom_events.edit` (Owner), `custom_events.delete` (Owner), `custom_events.reactivate` (Owner).

**Out of scope:**
- Ingest endpoint (Step 7).
- Bridges (Step 8).
- Workflow lifecycle cascades (Step 9).

## Files to touch
- `core/public_ingest/custom_events/{models.py (from Step 5), schemas.py, router.py, service.py, data_access.py, utils.py}`.
- `core/permissions/registry.py` (modified — 5 new keys).
- `main.py` (modified — router include).
- Tests.

## Plan
1. Pydantic schemas for request/response.
2. DAL (pure CRUD).
3. Service (business logic + validation + audit + `add_prefix` at write).
4. Router (endpoints + permission dependencies).
5. Register permissions.
6. Tests.

## DB changes / migrations
None (schema from Step 5).

## Tests to add
- `test_custom_event_create_auto_prefixes_at_publish_but_stores_raw`.
- `test_custom_event_create_rejects_reserved_system_event_name` — try `contact.created` → 400.
- `test_custom_event_create_rejects_unicode_homoglyph_via_ascii_regex`.
- `test_custom_event_create_partial_unique_case_insensitive_conflict_409`.
- `test_custom_event_soft_delete_partial_unique_allows_recreate`.
- `test_custom_event_edit_optimistic_lock_second_writer_409`.
- `test_custom_event_edit_emits_schema_diff_audit_event`.
- `test_custom_event_admin_can_create_view` (403 on edit/delete/reactivate).
- `test_custom_event_owner_only_edit_delete_reactivate`.
- `test_custom_event_rls_cross_tenant_read_empty`.
- `test_payload_schema_validation_types_and_caps`.

## Verification checklist
- Backend: all tests pass.
- Backend: audit-log inspection shows before/after diff on schema edit.
- Backend: permission keys registered (`GET /permissions/keys` lists all five).

## Self-check
- [ ] Rule 1-2: pure core, org_id + RLS.
- [ ] Rule 6: 5 new keys.
- [ ] Rule 8: ~7 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
