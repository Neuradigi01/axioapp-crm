# Step 6 — Templates list UI

**Goal:** Angular list page for `/user/templates` — filter by channel + status, search by name, status badges (both internal + external), per-row actions menu. The first frontend step in this track.
**Status:** Pending
**Depends on:** Step 3 (REST endpoints), Step 5 (sidebar entry).

---

## Scope

In-scope:
- `APP/.../core/templates/templates-api.service.ts` — typed Angular HTTP client wrapping the Step-3 endpoints. Follows the retry-interceptor convention (per `feedback_http_retry_interceptor.md` memory).
- `APP/.../core/templates/templates.page.{ts,html}` — list page:
  - Header: page title "Templates", "New template" button (gated on `templates.write`).
  - Filter bar: channel dropdown (all / WhatsApp / Email / SMS / Facebook Messenger / Instagram Direct / Push), status dropdown (all / Draft / In Review / Approved / Published / Archived), search input (debounced 300ms).
  - Table: name, channel chip, internal status badge (color-coded — gray draft / amber in-review / emerald approved / blue published / zinc archived), external status badge (only for WA + SMS-DLT; hidden otherwise), last updated, updated-by avatar, actions menu.
  - Empty state for new orgs: "No templates yet — create your first" CTA.
  - Pagination: 25 per page, next/prev.
- `APP/.../core/templates/template-status-badge.component.{ts,html}` — reusable badge for both internal + external statuses.
- `APP/.../core/templates/channel-chip.component.{ts,html}` — channel icon + label chip used in both list and editor.
- Route added to `APP/.../features/user/user.routes.ts` — lazy-loaded at `/user/templates`, guarded by `templates.read`.
- Jest smoke for the list page rendering + filter wiring.

Out of scope:
- Template editor (Step 7).
- Review modal / versions drawer / test-send modal (Step 8).
- Per-row action handlers other than "Open" — Edit / Submit / Approve / Publish / Archive come online in Step 7-8.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/templates/templates-api.service.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/templates.page.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/templates.page.html` | **NEW** |
| `APP/src/app/features/user/core/templates/template-status-badge.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/template-status-badge.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/channel-chip.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/channel-chip.component.html` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — add lazy route |
| `APP/src/app.config.ts` | edit — register any new Lucide icons used (`file-text`, `mail`, `message-circle`, `phone`, `bell`) |
| `APP/src/app/features/user/core/templates/templates.page.spec.ts` | **NEW** |

**~10 files. ~500 lines.**

## Plan

1. API service first — typed types for `Template`, `TemplateVersion`, `TemplateReview`, plus list/get/create/patch/archive methods.
2. Badge + chip components — small dumb components.
3. Page shell — header + filter bar + table + pagination.
4. Filter wiring — debounce search, sync filters into the API call.
5. Route + guard.
6. Lucide icons audited per `app.config.ts` memory (missing icon = silent template render failure).
7. Jest smoke: page renders empty state when API returns `[]`; channel filter changes triggers re-fetch.

## DB changes / migrations

None.

## Tests

3 Jest cases:
- Renders empty state when API returns no templates.
- Changing channel filter re-calls the API with the new query.
- Pagination next/prev triggers the right offsets.

## Smoke

```
1. ng serve, navigate to /user/templates.
2. Empty state visible for a fresh org.
3. As Owner, POST a couple templates via API (or seed). List shows them.
4. Channel filter dropdown narrows.
5. Status filter narrows.
6. Search input filters by name (debounced).
7. As Employee (templates.read only), "New template" button is hidden.
8. Click row → routes to /user/templates/{id} → 404 placeholder (Step 7 fills).
```

## Risks

- Missing Lucide icons crash the template silently per `feedback_lucide_icon_registry.md`. Audit all `<lucide-icon>` usages and confirm registry coverage before stop-report.

## Self-check (10 rules)

App lives under `features/user/core/templates/`. ✓ org_id auto-applied via existing JWT interceptor. ✓ N/A custom fields. ✓ N/A dynamic forms (template shapes are static — channel sub-forms come Step 7). ✓ Sidebar registered Step 5. Permission gate on route. ✓ pack.yaml untouched. ✓ 10 files / ~500 lines — at the upper bound; tests carry weight. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 6 — Templates list UI
Files: 10
Verify: /user/templates renders with filters + pagination + empty state + permission gate.
Tests: 3 Jest smoke cases.
Awaiting "proceed".
```
