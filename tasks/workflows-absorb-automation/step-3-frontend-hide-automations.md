# Step 3 — Frontend hide: sidebar entry + redirect resolver

**Goal:** Remove the "Automations" sidebar entry. Route `/user/automations/*` to `/user/workflows/*` via a resolver that uses the FK from Step 1 (`migrated_to_workflow_id`) to preserve deep-link bookmarks. Angular feature module code under `features/user/core/automation/` stays in place (imports removed from the route tree only).

**Status:** Pending

**Depends on:** Steps 1 + 2 (backend migrated + new seeds in place). Frontend hide before backend migration would strand users on empty redirects.

---

## Scope

In-scope:
- **Sidebar entry removed.** Wherever the layout module registers "Automations" — delete the entry, keep alphabetical ordering intact.
- **Route redirects** in `app/src/app/features/user/user.routes.ts`:
  - `/user/automations` → `/user/workflows`
  - `/user/automations/:id` → resolver looks up `migrated_to_workflow_id` via new backend endpoint `GET /api/v1/automations/{id}/migrated-workflow-id` → redirects to `/user/workflows/{workflow_id}`. Falls back to `/user/workflows` if the automation doesn't exist or wasn't migrated.
  - `/user/automations/:id/edit` → same resolver, then `/user/workflows/{workflow_id}/builder`.
  - `/user/automations/runs/:runId` → for now redirect to `/user/workflows` (no run-ID migration; legacy runs remain queryable via API for support purposes).
- **New backend endpoint** `GET /api/v1/automations/{automation_id}/migrated-workflow-id` returns `{workflow_id: UUID | null}` — reads `tbl_automations.migrated_to_workflow_id` (via DAL helper from Step 1). Standard Owner+Admin permission (same as the existing automation-view scope).
- **Angular feature module code preserved.** `features/user/core/automation/` folder, its components, services — untouched. Only the route registration is removed. Follows manager directive "do not delete or remove its code".
- **Small toast** in the frontend `RedirectAutomationResolver`: shows an info snackbar "Automations are now part of Workflows" the first time a redirect resolves. Uses `localStorage` flag `automation-redirect-seen` so it only shows once per browser.

Out of scope:
- Any change to `features/user/core/automation/` components. They stay dormant.
- Removing the `AutomationService` HTTP client — kept in case future admin tooling needs read access.
- Backend automation router deletion — kept, per manager directive.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/layout/sidebar/*.ts` | edit — remove "Automations" entry from the nav registry (find the registration, delete the entry, adjust adjacent entries' order if needed) |
| `app/src/app/features/user/user.routes.ts` | edit — remove the automation route branch; add `{ path: 'automations', … RedirectAutomationResolver }`, `{ path: 'automations/:id', … }`, `{ path: 'automations/:id/edit', … }`, `{ path: 'automations/runs/:runId', redirectTo: 'workflows' }` |
| `app/src/app/features/user/core/workflows/redirect-automation.resolver.ts` | **NEW** — Angular resolver: takes automation id from URL, calls `GET /api/v1/automations/:id/migrated-workflow-id`, returns a `Router.createUrlTree(['/user/workflows', workflow_id])`. Falls back to `/user/workflows` on 404 or null. Shows one-time toast. |
| `api/src/app/core/automation/router.py` | edit — add endpoint `GET /automations/{automation_id}/migrated-workflow-id` calling `service.get_migrated_workflow_id(...)` |
| `api/src/app/core/automation/service.py` | edit — add `get_migrated_workflow_id(db, *, automation_id, current_user) -> UUID \| None` — permission check + call to `data_access.find_by_id` returning `migrated_to_workflow_id` |
| `app/tests/features/user/core/workflows/redirect-automation.resolver.spec.ts` | **NEW** — 4 Angular unit tests: happy path, 404 fallback, null-FK fallback, toast-shown-once |

**~6 files. ~300 lines.**

## Plan

1. **Backend endpoint first** — needed by the frontend resolver. Uses the DAL helper `find_by_id` (existing) — no new DAL work. Service returns `automation.migrated_to_workflow_id`. Router returns `{workflow_id: str | None}`.
2. **Frontend resolver** — Angular functional resolver (`ResolveFn`) using `inject(HttpClient)` and `inject(Router)`. Returns `MaybeAsync<UrlTree>`.
3. **Route table** — swap the automation feature route branch for four redirect entries (list, detail, edit, runs). Detail + edit use the resolver; list + runs use static `redirectTo`.
4. **Sidebar** — one-line entry removal.
5. **Toast** — inject `MatSnackBar` in the resolver, check `localStorage.getItem('automation-redirect-seen')` before showing, set flag after. Copy: "Automations are now part of Workflows. Redirected to the Workflows page."
6. **Prettier + eslint** on new files per `feedback_prettier_on_write.md`.

## Tests

**Backend** — 2 pytest cases (add to existing `test_automation_router.py`):
- `test_migrated_workflow_id_endpoint_returns_workflow_id_when_set`
- `test_migrated_workflow_id_endpoint_returns_null_when_not_migrated`

**Frontend** — 4 Karma cases in `redirect-automation.resolver.spec.ts`:
- `resolves_to_workflow_url_tree_when_backend_returns_workflow_id`
- `resolves_to_workflows_list_when_backend_returns_null`
- `resolves_to_workflows_list_on_404`
- `shows_toast_only_once_per_browser`

## Smoke (post-Step-3, on Ajay's Workspace)

```
1. Log into Ajay's Workspace at /user/dashboard.
2. Sidebar → confirm "Automations" entry is gone.
3. Direct-navigate to /user/automations.
   → Should land on /user/workflows.
   → Toast "Automations are now part of Workflows" shows.
4. Refresh, navigate to /user/automations again.
   → Same redirect, NO toast (already seen).
5. Copy an automation UUID from Ajay's Workspace (any row from tbl_automations where org_id matches).
   Navigate to /user/automations/<that-uuid>.
   → Should land on /user/workflows/<the-migrated-workflow-uuid>.
6. Navigate to /user/automations/00000000-0000-0000-0000-000000000000 (non-existent).
   → Falls back to /user/workflows (list).
7. In Workflows list, confirm all rows visible; single-step and multi-step mixed; filters work.
8. Open one migrated workflow (name matches an old automation). Confirm builder shows the trigger + single send node (or wait+send if delay was set).
```

## Risks

- **Existing browser tabs / bookmarked deep-links.** After deploy, any tab still open on `/user/automations` will 404 unless the router picks up the new route table. Angular routes are static per bundle — a tab open pre-deploy on `/user/automations/some-id` will hit the OLD frontend (which serves the automation feature module) until refresh. **Non-issue** — refresh loads the new bundle, redirect fires. Document in release notes.
- **Sidebar entry cached in signal state.** The layout module may cache the nav list in a signal on init. Confirm the removal takes effect on hot reload (dev) and after cache-bust (prod).
- **Resolver + async CanActivate ordering.** If a guard runs before the resolver, ensure the guard also handles the automation route (either permit or delegate to resolver). Test path: unauthenticated user hits `/user/automations` → should redirect to `/accounts/login`, not run resolver.

## Self-check (10 rules · layering · reuse · DB efficiency · tooling-clean)

- ✓ `core` never imports from `packs`. N/A.
- ✓ `org_id` on every read — endpoint uses standard auth-scoped current-user + org-scoped DAL.
- ✓ `tbl_` prefix — N/A.
- ✓ Custom fields — N/A.
- ✓ Sidebar removal — this IS the sidebar change.
- ✓ Permissions — endpoint reuses existing automation-view scope; RBAC unchanged.
- ✓ Pack manifest — untouched.
- ✓ Step size — 6 files, ~300 lines. Within threshold.
- ✓ Stop-and-report.
- ✓ No TODOs.
- ✓ Layering — router calls service, service calls DAL. Router has NO SQL. Service has NO SQL. DAL helper already exists (added in Step 1).
- ✓ Reuse — `find_by_id` DAL helper already exists; new service method wraps it.
- ✓ DB efficiency — one PK lookup per redirect.
- ✓ Tooling — prettier + eslint run on new .ts files per `feedback_prettier_on_write.md`. `run lint` passes.

## Stop & report

```
Step 3 — Frontend hide: sidebar + redirect resolver
Files: 6
Verify:
  - Sidebar "Automations" entry gone.
  - /user/automations → /user/workflows (with one-time toast).
  - /user/automations/:id → /user/workflows/<migrated_id> when FK exists; falls back to list otherwise.
  - Deep-link bookmarks preserved via resolver.
Tests: 2 pytest + 4 Karma cases.
Self-check: all pass.
Awaiting your "proceed".
```
