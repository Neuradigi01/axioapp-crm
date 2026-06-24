# Step 3 — Trigger router and permissions

**Goal:** REST endpoints for trigger CRUD + run-history read. Register three new permission keys and mount the router under `/api/v1/automations`.
**Status:** Pending
**Depends on:** Step 1 (schema), Step 2 (service).

---

## Scope

In-scope:
- `core/automation/router.py` — endpoints:
  - `GET /api/v1/automations/triggers` — list (filters: `event_type`, `enabled`, `channel`, `q`). Gated on `automations.read`.
  - `POST /api/v1/automations/triggers` — create. Gated on `automations.write`.
  - `GET /api/v1/automations/triggers/{id}` — read. Gated on `automations.read`.
  - `PATCH /api/v1/automations/triggers/{id}` — edit. Gated on `automations.write`.
  - `POST /api/v1/automations/triggers/{id}/enable` — toggle on. Gated on `automations.write`.
  - `POST /api/v1/automations/triggers/{id}/disable` — toggle off. Gated on `automations.write`.
  - `DELETE /api/v1/automations/triggers/{id}` — delete. Gated on `automations.write`.
  - `GET /api/v1/automations/triggers/{id}/runs` — paginated run history (filters: `status`, `since`, `limit`, `offset`). Gated on `automations.runs.read`.
  - `GET /api/v1/automations/event-types` — discovery: returns the registered event-type taxonomy (label + sample payload shape per event). Gated on `automations.read`. Editor (Step 8) uses this for the event picker.
- Three new permission keys: `automations.read`, `automations.write`, `automations.runs.read`. Registered via `core/automation/permissions.py`.
- Owner + Admin role templates get all three keys; Employee gets `read` only.
- Backfill migration `<ts>_bf_automations_perm.py` adds the keys to existing Owner/Admin role rows.
- Router mounted from `main.py`.
- API tests covering each endpoint.

Out of scope:
- Module descriptor / sidebar entry (Step 7 — registered alongside the UI).
- Dispatcher (Step 4).
- Manual trigger fire from the UI ("Run now" button) — Step 9.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/router.py` | **NEW** |
| `API/src/app/core/automation/permissions.py` | **NEW** |
| `API/alembic/versions/<ts>_bf_automations_perm.py` | **NEW** — backfill |
| `API/src/app/main.py` | edit — mount router |
| `API/src/app/core/auth/role_templates.py` | edit — add three keys |
| `API/tests/automation/test_router.py` | **NEW** |

**~6 files. ~400 lines.**

## Plan

1. Permissions module: declare key constants.
2. Router: thin endpoints calling Step-2 service.
3. Event-types discovery endpoint: returns a static dict keyed by event-type string with `label`, `description`, `sample_payload`. Lives in `core/automation/event_catalog.py` (small new file).
4. Backfill migration for existing tenants.
5. Mount router in main.
6. Tests cover all endpoints + tenant isolation + permission gating.

## DB changes / migrations

One backfill migration — no schema change.

## Tests

10 pytest cases:
- List returns only my-org triggers.
- Create requires `automations.write`.
- Patch increments updated_at + records updated_by.
- Enable/disable idempotent.
- Delete forbidden if any runs reference it without CASCADE — confirm CASCADE works.
- Run history filtered by status.
- Run history paginated.
- Event-types discovery returns the full taxonomy.
- Channel/template mismatch on create returns 422.
- Cross-org read returns 404 (RLS).

## Smoke

```
1. POST /api/v1/automations/triggers {name, event_type: "lead.created", channel: "email", template_id: ..., delay_seconds: 0, recipient_resolver: "contact.email"} → 200 with enabled=true by default.
2. GET /api/v1/automations/triggers → returns it.
3. PATCH ... {enabled: false} → toggles.
4. GET /api/v1/automations/event-types → returns the catalog (user.signed_up, lead.created, etc).
5. As Employee (read-only), POST returns 403.
```

## Risks

- Event catalog needs to stay in sync with what's actually publishable. Catalog defines the contract; emit calls in Steps 5/6/10/11/12 must match. Pin test in `tests/automation/test_event_catalog_consistency.py` (Step 5+) ensures every emit's event_type is in the catalog.
- Permission backfill must be idempotent (skip already-present keys). Mirror existing `0095_bf_*` pattern.

## Self-check (10 rules)

`core/automation/`. ✓ org_id on every endpoint. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 7). Permissions registered. ✓ pack.yaml untouched. ✓ 6 files / ~400 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 3 — Trigger router and permissions
Files: 6
Verify: nine REST endpoints + three perm keys registered + role templates updated + backfilled on existing Owner/Admin.
Tests: 10 pytest cases.
Awaiting "proceed".
```
