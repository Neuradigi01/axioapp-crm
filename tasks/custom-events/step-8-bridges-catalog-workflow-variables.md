# Step 8 — Bridges: catalog merge (service layer) + workflow trigger picker + variables registry payload-schema bridge

**Goal:** merge custom events into the workflow trigger picker via a service-layer function (`event_catalog.list_catalog()` stays pure). Add a bridge in `core/variables/service.py` so `event=<custom.name>` in `/variables` returns the custom event's payload_schema keys as `event.*` variables.
**Phase:** Custom Events track — step 8/17
**Depends on:** Steps 5, 6, 7c, Track A Step 5 (if shipped)
**Status:** Pending

## Scope

**In-scope:**
- `core/public_ingest/custom_events/service.list_catalog_for_org(session, org_id) -> list[dict]` — returns system events (from `event_catalog.list_catalog()`) + custom events (from `tbl_custom_events` where `is_active=true`) as a merged, ordered list with a `category` field distinguishing them. `event_catalog.py` stays pure (module-import contract preserved).
- `core/workflows/service.py` (or wherever trigger-picker endpoint lives): `GET /api/v1/workflows/event-catalog?org_id=<from_context>` returns merged catalog. Frontend picker auto-groups by `category`.
- `core/variables/service.py` (Track A extension): when `event=<name>` is passed, if the event name starts with `custom.`, query `tbl_custom_events` for its `payload_schema` and emit each declared property as `event.<property_name>` in the event group. Applies existing `is_visible_to` filter equivalent (custom events are org-scoped so RLS handles cross-org).
- If Track A hasn't shipped: this step patches ONLY the workflows trigger picker (targeted change); variables registry integration deferred until Track A ships.

**Out of scope:**
- Workflow lifecycle cascades (Step 9).
- Retention (Step 10).

## Files to touch
- `core/public_ingest/custom_events/service.py` (modified — add `list_catalog_for_org`).
- `core/workflows/service.py` and `router.py` (modified — event-catalog endpoint uses merged list).
- `core/variables/service.py` (modified if Track A shipped) OR `APP/.../workflows/trigger-picker/*.ts` (modified if Track A hasn't).
- Tests.

## Plan
1. Service-layer merge function.
2. Workflow-catalog endpoint updated.
3. Variables registry bridge (or fallback patch).
4. Tests.

## Tests to add
- `test_list_catalog_for_org_returns_system_plus_active_custom_events`.
- `test_list_catalog_for_org_hides_soft_deleted_custom_events`.
- `test_list_catalog_for_org_rls_cross_tenant`.
- `test_event_catalog_module_still_pure` — importable, no DB.
- `test_variables_endpoint_event_group_for_custom_event_returns_payload_schema_keys` (only if Track A shipped).
- `test_workflows_trigger_picker_ui_shows_custom_events_grouped_by_category` (Playwright).

## Verification checklist
- Backend: tests pass.
- Backend: `event_catalog.list_catalog()` still callable without a session (pure).
- Frontend: workflow trigger picker groups system vs custom events.

## Self-check
- [ ] Rules clean.
- [ ] Rule 8: 4 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
