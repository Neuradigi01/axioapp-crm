# Step 3 — Trigger router and permissions

**Goal:** REST endpoints for trigger CRUD + run-history read. Register three new permission keys and mount the router under `/api/v1/automations`.
**Status:** COMPLETED — Migration `0127_bf_automations_perm` registers the three keys (`automations.read` / `automations.write` / `automations.runs.read`) in `tbl_permissions` AND fans the grants out to existing Owner/Admin (all three keys × 23 orgs = 69 grants each) + Employee (read only × 23 = 23 grants) — DB confirms post-apply. Idempotent `INSERT … ON CONFLICT DO NOTHING` pattern mirrors `0118_bf_templates_perm`. Downgrade revokes + removes the keys. NEW `core/automation/permissions.py` (`PERM_READ` / `PERM_WRITE` / `PERM_RUNS_READ` constants + `ALL_KEYS` tuple — single source for the role-template + backfill imports). `core/permissions/role_templates.py` extended: Admin gets all three keys (in `_CORE_ADMIN_KEYS` so Owner inherits them via `_CORE_ADMIN_KEYS + …`); Employee gets `automations.read` only (sidebar entry visible, mutations gated). NEW `core/automation/event_catalog.py` — discovery catalog typed via `CatalogEntry(event_type, label, description, sample_payload)`. 12 entries seeded covering the manager's spec'd v1 events: auth/onboarding (`user.signed_up` / `user.invited` / `user.invitation_accepted`), leads (`lead.created` / `lead.status_changed` / `lead.score_threshold` / `contact.birthday`), appointments (`appointment.booked` / `appointment.reminder_24h` / `appointment.reminder_1h`), sales (`quote.sent` / `quote.accepted` / `invoice.sent` / `invoice.overdue_7d`). `list_catalog()` returns deterministic `event_type ASC` so the editor picker (Step 8) renders the same order every render. `is_known()` helper for Step 5+'s pin-test that walks every `bus.publish` call. `core/automation/data_access.py` extended with `list_runs(org_id, trigger_id?, status?, since?, limit, offset)` — uses the `ix_automation_runs_trigger_scheduled_desc` index from Step 1 (descending) so newest fires sit at the top. NEW `core/automation/router.py` mounting 9 endpoints under `/api/v1/automations`: trigger CRUD (`GET /triggers` list with channel/event/enabled/q filters, `POST /triggers` create, `GET /triggers/{id}` read, `PATCH /triggers/{id}` edit, `POST /triggers/{id}/enable`, `POST /triggers/{id}/disable`, `DELETE /triggers/{id}` → 204 NO_CONTENT), `GET /triggers/{id}/runs` run history (gated tighter on `automations.runs.read` because run payloads carry contact data + the trigger-existence pre-check ensures the runs path 404s for cross-org / missing triggers), `GET /event-types` discovery. Centralised `_automation_http_map(AutomationError)` converts service exceptions to structured `{detail: {code, message}}` responses: `TriggerNotFound → 404`, `DuplicateTriggerName → 409`, `InvalidCondition + MissingTemplateForChannel → 422`. `main.py` extended with the include line right after the templates router include (matches the related-modules locality pattern). 8 pytest cases in `test_router.py` (empty list, create+read happy, write-perm gating returns 403, channel/template mismatch returns 422 with `code='automation.template_channel_mismatch'`, invalid condition returns 422 with `code='automation.invalid_condition'`, duplicate name case-insensitive returns 409, PATCH updates fields, enable/disable idempotent, delete returns 204 + subsequent GET returns 404, runs endpoint refuses without `automations.runs.read` perm, event-types discovery returns `user.signed_up` + `lead.created`) + 7 pytest cases in `test_event_catalog.py` pinning the catalog's contract (manager-required events present, sales/appointment events present, deterministic sort order, every entry has label/description/non-empty sample_payload, `lead.created` payload carries the expected variable paths). Pytest run deferred per `feedback_pause_before_pytest.md` baseline.
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
