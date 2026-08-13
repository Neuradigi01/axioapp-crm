# Step 3 — Router + permissions + sidebar module registration

**Goal:** Expose the Step 2 service via REST endpoints under `/api/v1/chatbots`, register permission keys, and register the sidebar module descriptor so the frontend can list it.
**Depends on:** Step 2
**Status:** Pending

## Scope

**In-scope**
- `core/chatbots/router.py` — all REST endpoints (list, get, create, update, delete/archive, publish, pause, version history, save-target picker).
- `core/chatbots/module.py` — sidebar module descriptor + permission key registration.
- Permission keys: `chatbots.view`, `chatbots.edit`, `chatbots.publish`, `chatbots.delete`.
- Wire `include_router(...)` from `main.py` (or the auto-registration file, whichever is in use).

**Out of scope**
- Trigger-dispatch subscriber — Step 5.
- Test-fire endpoint (needs engine) — Step 6.
- Signed-URL interstitial — Step 11.
- Frontend consuming these endpoints — Steps 12+.

## Files to touch

- `API/src/app/core/chatbots/router.py` (created)
- `API/src/app/core/chatbots/module.py` (created)
- `API/src/app/main.py` (modified — include the chatbots router) OR the module auto-registration file
- `API/src/app/core/permissions/data_access.py` or seed file (modified — add 4 permission keys)

## Plan

1. `router.py` — endpoints:
   - `GET /api/v1/chatbots` — list with filters `?status=&category=&folder_id=&q=`
   - `GET /api/v1/chatbots/{id}` — read with graph
   - `POST /api/v1/chatbots` — create; body `ChatbotCreate`
   - `PATCH /api/v1/chatbots/{id}` — update; body includes `expected_version`; 409 on mismatch
   - `POST /api/v1/chatbots/{id}/publish` — status → `live`; requires `chatbots.publish`; audit event
   - `POST /api/v1/chatbots/{id}/pause` — status → `paused`
   - `DELETE /api/v1/chatbots/{id}` — soft delete (status → `archived`); requires `chatbots.delete`
   - `GET /api/v1/chatbots/{id}/versions` — list past versions
   - `POST /api/v1/chatbots/{id}/versions/{version_id}/rollback` — restore prior graph
   - `GET /api/v1/chatbots/save-targets?entity=contact` — picker source (see Step 2)
   - **No `db.execute/add/etc` in router** — call service functions only.
2. Every endpoint takes an auth dependency that injects `current_user + org_id`; org_id resolves from JWT context per rule #2.
3. `module.py` — sidebar descriptor: `id=chatbots, label="Chat Bots", icon="bot", route="/user/chatbots", required_permission="chatbots.view", position=<between workflows and reports>`; permission key registration for the four keys with descriptions.
4. Wire the module in the app-startup module registry (rule #5).

## DB changes / migrations

None. Permission keys are seed data — INSERT in a small alembic seed migration or via the existing permissions-seeder helper depending on repo convention. Idempotent inserts.

## Tests to add

Location: `API/tests/core/chatbots/test_router.py`

- `test_list_requires_view_permission`
- `test_create_requires_edit_permission`
- `test_publish_requires_publish_permission`
- `test_delete_requires_delete_permission`
- `test_stale_version_returns_409`
- `test_save_targets_endpoint_excludes_sensitive`
- `test_cross_org_get_returns_404` — bot in org A not visible to org B.
- `test_sidebar_module_registered` — hits the module-registry list endpoint.

## Verification checklist

**Backend**
- [ ] Router pin-test green (no `db.execute/add/select/insert/update/delete` imports in router.py).
- [ ] All endpoints return correct 401/403/404/409 shapes.
- [ ] Swagger UI at `/docs` shows the chatbots section with all endpoints.
- [ ] `GET /api/v1/module-registry` returns the chatbots descriptor.

**Frontend** — N/A this step.

**Code review**
- [ ] Router imports only from `service.py` — never from another module's DAL (layered rule).
- [ ] Permission checks server-side, not just frontend guards (attacker-review C2 hardening).

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` scoped in every service call
- [ ] Sidebar registry updated (rule #5)
- [ ] Permission registry updated (rule #6)
- [ ] Under 10 files, under 400 lines
- [ ] Zero TODOs

## Stop & report

Report endpoint list with permission keys per route, and the INSERT SQL for the four permission keys. Await "proceed".
