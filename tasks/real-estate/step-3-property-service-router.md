# Step 3 — Property backend: service, router, module descriptor (CRUD)

**Goal:** Ship the authenticated CRUD API surface for Property under `/api/v1/property/*` — create, list (with filters + pagination), get one, update, delete, publish, unpublish, archive, mark-sold. Register the module descriptor so it appears in the sidebar for orgs on the Real Estate pack with the right permissions.

**Track:** Real Estate CRM Pack
**Status:** Pending
**Depends on:** Step 2 (models + DAL).

---

## Scope

**IN:**

1. `schemas.py` — complete Pydantic v2 request models:
   - `PropertyCreate` — required: `title`, `property_type`, `category`. Optional: everything else per Step 2 model (except system-owned fields like `id`, `owner_id`, `org_id`, `status`, timestamps).
   - `PropertyUpdate` — every field optional (partial update).
   - `PropertyListFilters` — status (multi-select), property_type, category, city, min_price, max_price, bedrooms, search (title ILIKE), sort_by (`created_at | updated_at | price | title`), sort_order.
   - `PropertyStatusChange` — used by publish/unpublish/archive/mark-sold endpoints (empty body; the action verb is in the URL).
   - `PropertyListOut` — pagination envelope: `{items: list[PropertyOut], total: int, page: int, page_size: int, status_counts: {draft: 3, published: 7, ...}}`.

2. `service.py` — business logic + the only layer that commits:
   - `create_property(db, *, org_id, actor_user_id, payload) -> Property`:
     - Validate enums (property_type, category).
     - Generate slug from title (`slugify(title) + short-random-suffix` to guarantee uniqueness within org).
     - Set `status="draft"`, `owner_id=actor_user_id`, `currency` from org_settings if payload omits it.
     - Call `data_access.insert_property` → `db.flush()` → `db.commit()` → `db.refresh()`.
     - Emit audit-log event `property.created`.
     - Return `PropertyOut`.
   - `list_properties(db, *, org_id, actor_user_id, filters, page, page_size) -> PropertyListOut`:
     - Apply filters + pagination via DAL.
     - Eager-load images (`selectinload(Property.images)`) — Rule: no N+1.
     - Compute `status_counts` via DAL's `count_properties_by_status`.
     - Return one-round-trip result (2 queries: main list + status counts).
   - `get_property(db, *, org_id, actor_user_id, property_id) -> PropertyOut`:
     - Fetch via DAL; if missing → 404.
     - Eager-load images.
   - `update_property(db, *, org_id, actor_user_id, property_id, payload) -> PropertyOut`:
     - Fetch → verify not archived/sold (or allow with a warning; decide during review — draft says: disallow edits on `sold` / `archived`, allow on `draft` / `published` / `unpublished`).
     - Apply patch; regenerate slug only if title changed.
     - Commit; audit `property.updated`.
   - `delete_property(db, *, org_id, actor_user_id, property_id) -> None`:
     - Hard delete + cascade of images (physical files cleaned in Step 4's service via a hook).
     - Permission check: `property.delete`.
     - Audit `property.deleted`.
   - `publish_property(db, *, org_id, actor_user_id, property_id) -> PropertyOut`:
     - Validate: must have `title`, `property_type`, `category`, at least one image (Rule: no unpublishable-shell listings). Reject with 422 if not.
     - Set `status="published"`, `published_at=now()`.
     - Commit; audit `property.published`.
   - `unpublish_property(db, ...)` — set `status="unpublished"`.
   - `archive_property(db, ...)` — set `status="archived"`, `archived_at=now()`.
   - `mark_sold(db, ...)` — set `status="sold"`, `sold_at=now()`.
   - All state transitions validated (draft → published → unpublished ↔ published → archived; sold from published only). A `_valid_transitions` map in the service.

3. `router.py` — endpoints (no SQL, no `db.execute`; only calls to service):
   - `POST /api/v1/property` — create. Permission: `property.write`.
   - `GET /api/v1/property` — list with filters + pagination + status_counts. Permission: `property.read`.
   - `GET /api/v1/property/{id}` — detail. Permission: `property.read`.
   - `PATCH /api/v1/property/{id}` — update. Permission: `property.write`.
   - `DELETE /api/v1/property/{id}` — delete. Permission: `property.delete`.
   - `POST /api/v1/property/{id}/publish` — publish. Permission: `property.publish`.
   - `POST /api/v1/property/{id}/unpublish` — unpublish. Permission: `property.publish`.
   - `POST /api/v1/property/{id}/archive` — archive. Permission: `property.archive`.
   - `POST /api/v1/property/{id}/mark-sold` — mark sold. Permission: `property.write` (deal outcome).
   - All endpoints use the standard `Depends(get_current_org_context)` (org_id + actor_user_id + granted permissions) — no new dep needed; the pattern from Furniture pack modules is reused.

4. `module.py` — module descriptor:
   ```python
   MODULE = ModuleDescriptor(
       id="property",
       name="Properties",
       icon="home",
       layer="pack",
       route="/api/v1/property",
       frontend_route="/user/properties",
       menu_position=15,           # slots after Dashboard (10), before Contacts (20)
       permissions=[
           "property.read", "property.write",
           "property.publish", "property.archive", "property.delete",
       ],
   )
   ```

5. Router mounted in the app's central router. Mirror how Furniture inventory router is mounted — search for `include_router(inventory_router` in the app startup to find the exact pattern, add an analogous line for property.

6. Pytest — `test_property_service.py`:
   - `test_create_property_ok` — happy path.
   - `test_publish_requires_image` — publishing a property with no images returns 422.
   - `test_publish_transitions_state_and_timestamps` — status becomes `published`, `published_at` is set.
   - `test_update_regenerates_slug_on_title_change` — slug recomputed only when title changes.
   - `test_delete_cascades_images` — deleting a property removes all its image rows.
   - `test_permission_denied_on_read_without_grant` — a user without `property.read` gets 403.
   - `test_org_isolation` — user in org A cannot fetch a property from org B (returns 404, not 403; don't leak existence).

**OUT:**

- No image upload endpoint — Step 4.
- No public routes — Step 5.
- No frontend — Steps 6–8.

## Files touched

| File | Change |
|---|---|
| `api/src/app/packs/real_estate/modules/property/schemas.py` | Modify — add ~150 lines of complete request/response schemas. |
| `api/src/app/packs/real_estate/modules/property/service.py` | New (~280 lines). |
| `api/src/app/packs/real_estate/modules/property/router.py` | New (~140 lines). |
| `api/src/app/packs/real_estate/modules/property/module.py` | New (~30 lines). |
| `api/src/app/main.py` (or the routers-mount file) | Modify — 1 line: `app.include_router(property_router)`. |
| `api/tests/packs/real_estate/test_property_service.py` | New (~200 lines). |

**6 files, ~800 lines total.** Within Rule 8 (each file < 400, verifiable end-to-end via a Postman/curl walk-through of the 9 endpoints).

## Verification checklist

- [ ] Restart backend → new endpoints appear in `/docs` (Swagger).
- [ ] Create a property via `POST /api/v1/property` — returns 201 with the created object.
- [ ] List → the created property appears.
- [ ] Publish without images → 422 with clear message.
- [ ] Update title → slug regenerates.
- [ ] Try to fetch from a different org's session → 404.
- [ ] `uv run pytest tests/packs/real_estate/test_property_service.py -v` — 7 assertions green.
- [ ] `test_layered_architecture_convention.py` still green.
- [ ] Sidebar auto-shows "Properties" entry (frontend still needs Step 6 to actually render the page, but the module discovery endpoint returns it).

## Self-check against the 10 rules

- **Rule 1** — Property module lives in `packs/real_estate/`; no imports from `core/` outward.
- **Rule 5** — Sidebar entry via `ModuleDescriptor` — auto-registered, no core edit.
- **Rule 6** — Permission keys declared on the descriptor and consumed in `router.py` via existing `require_permission("property.write")` dep helper.
- **Rule 8** — Step scope covers a single CRUD surface; can be reviewed end-to-end in a Postman walk-through.
- **Rule 10** — All 9 endpoints production-ready; no TODOs, no `raise NotImplementedError`.
- **Layering** — Service is the only file with `db.commit / flush / refresh`. Router only calls service. DAL untouched from Step 2. Pin-test verifies.
- **DB efficiency** — List endpoint uses `selectinload` for images + one aggregate query for status counts = 2 round-trips regardless of page size.

## Stop and report

- **Files changed:** 6 files.
- **What you can verify:** `/docs`, curl walk-through of 9 endpoints, pytest.
- **Tests added:** 7 assertions.
- **Self-check:** 10 rules + layering pin-test.
- **Awaiting 'proceed'** — Step 4 layers on multi-image upload / gallery management.
