# Step 7 — Saved views (backend + UI) + Lead scoring rules admin page

**Goal:** persist a user's current filter + sort + columns + scope as a named "view" that they can re-apply with one click, and optionally share with their team. Add a Settings → Lead Scoring page where Owners/Admins can manage the rules whose engine shipped in Step 5. After this step the leads track is done and the same saved-views pattern is reusable for contacts, walk-ins, tasks, etc.

**Depends on:** Step 5 (filter DSL + scoring rule CRUD endpoints) and Step 6 (advanced filter modal + column prefs).

## Files changed

### New backend
- `API/alembic/versions/0071_saved_views.py`
- `API/src/app/core/saved_views/models.py`
- `API/src/app/core/saved_views/schemas.py`
- `API/src/app/core/saved_views/service.py`
- `API/src/app/core/saved_views/router.py`
- `API/src/app/core/saved_views/module.py`

### Modified backend
- `API/src/app/main.py` — register saved_views router + module.

### New tests
- `API/tests/core/saved_views/test_saved_views.py`

### New frontend
- `APP/src/app/features/user/core/leads/saved-views-api.service.ts`
- `APP/src/app/features/user/core/settings/lead-scoring-rules.page.ts` *(standalone, inline template)*

### Modified frontend
- `APP/src/app/features/user/core/leads/leads.page.ts` — saved-view state + apply/save handlers.
- `APP/src/app/features/user/core/leads/leads.page.html` — saved-views dropdown menu in the toolbar (inline).
- `APP/src/app/features/user/user.routes.ts` — add `settings/lead-scoring` route.

**Total: 12 files (7 new backend incl. test, 1 modified backend, 2 new FE, 3 modified FE).**

## Migration `0071_saved_views.py`

- `CREATE TABLE saved_views (`
  - `id UUID PRIMARY KEY DEFAULT gen_random_uuid(),`
  - `org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,`
  - `owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,`
  - `entity VARCHAR(32) NOT NULL,` *(`'leads'` for now; extensible to `'contacts'`, `'walk_ins'`, etc.)*
  - `name VARCHAR(80) NOT NULL,`
  - `config JSONB NOT NULL,` *(see shape below)*
  - `shared BOOLEAN NOT NULL DEFAULT FALSE,`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`
- `CREATE UNIQUE INDEX uq_saved_views_owner_entity_name ON saved_views (owner_user_id, entity, name)`
- `CREATE INDEX ix_saved_views_org_entity ON saved_views (org_id, entity)`
- RLS on `saved_views`: visible row = `org_id = current_org` AND (`owner_user_id = current_user` OR `shared = TRUE`). Per Rule 2.
- `downgrade()` drops the policy, indexes, table.

### `config` JSONB shape

```json
{
  "filter": { "all": [{"field":"status","op":"eq","value":"qualified"}] },
  "sort": "lead_score",
  "order": "desc",
  "scope": "team",
  "columns": [
    {"key":"contact_name","label":"Contact","visible":true},
    {"key":"lead_score","label":"Score","visible":true},
    ...
  ],
  "view": "list"
}
```

All four fields optional individually — missing keys mean "use the page default."

## `saved_views/models.py`

Standard `SavedView` model. Foreign keys to `Organization` and `User`. Mapped `JSONB` for `config`. No relationship back-population needed.

## `saved_views/schemas.py`

```python
class SavedViewConfig(BaseModel):
    filter: dict | None = None
    sort: str | None = None
    order: Literal["asc", "desc"] | None = None
    scope: Literal["mine", "team", "all"] | None = None
    columns: list[dict] | None = None
    view: Literal["list", "pipeline"] | None = None

class SavedViewCreate(BaseModel):
    entity: Literal["leads"]    # widen later
    name: str = Field(min_length=1, max_length=80)
    config: SavedViewConfig
    shared: bool = False

class SavedViewUpdate(BaseModel):
    name: str | None = None
    config: SavedViewConfig | None = None
    shared: bool | None = None

class SavedViewOut(SavedViewCreate):
    id: UUID
    owner_user_id: UUID
    created_at: datetime
    updated_at: datetime
```

`filter` is left as `dict` (not `FilterDsl`) so the schema doesn't pull in the leads DSL — saved_views stays a generic infrastructure module. The leads page is responsible for shape-validating its own `config.filter` before sending.

## `saved_views/service.py`

- `list_views(session, *, org_id, user_id, entity) -> list[SavedView]` — returns owned + shared, sorted alphabetically (owned first).
- `create_view(session, *, org_id, user_id, payload) -> SavedView` — uniqueness on (`owner_user_id`, `entity`, `name`); collision → `409`.
- `update_view(session, *, view_id, user_id, payload) -> SavedView` — only the owner can update; otherwise `403`. `shared` toggles between owner-only and team-visible.
- `delete_view(session, *, view_id, user_id) -> None` — only owner can delete; `403` otherwise.

No "transfer ownership" in v1; if owner is deactivated, the view becomes inaccessible (matches CRM conventions).

## `saved_views/router.py`

| Method | Path | Notes |
|---|---|---|
| `GET` | `/saved-views?entity=leads` | `tasks.read` is not the right key — uses a new `saved_views.use` (granted to every authenticated user by the module). Lists owned + shared. |
| `POST` | `/saved-views` | `saved_views.use` |
| `PATCH` | `/saved-views/{id}` | Owner-only enforced in service. |
| `DELETE` | `/saved-views/{id}` | Owner-only enforced in service. |

## `saved_views/module.py`

Register one permission key:
- `saved_views.use` — granted to every role template (it's a personal productivity feature, not a privilege).

## `main.py`

`app.include_router(saved_views_router, prefix="/api/v1", tags=["saved-views"])` + import the module so its permission key registers at startup.

## `saved-views-api.service.ts`

Standard Angular HTTP service. Methods: `list(entity)`, `create(payload)`, `update(id, payload)`, `delete(id)`. Uses the project's HTTP retry interceptor (per feedback memory) — no special handling.

## `leads.page.ts` — saved-views integration

```typescript
readonly savedViews = toSignal(this.savedViewsApi.list('leads'), { initialValue: [] });
readonly currentViewId = signal<UUID | null>(null);
readonly currentViewName = computed(() =>
  this.savedViews().find(v => v.id === this.currentViewId())?.name ?? null
);
```

Handlers:
- `applyView(view: SavedView)` — sets all of: filter, sort/order, scope, columns, list/pipeline view, advanced filter signal. Resets cursor to null. Refetches.
- `saveCurrentAsView()` — opens an inline "Save view" mini-modal (name + share-with-team checkbox). On confirm, builds `config` from current state and POSTs.
- `updateCurrentView()` — POSTs the current state under the current view id. Disabled when no view is active or caller isn't the owner.
- `deleteCurrentView()` — confirm dialog → DELETE → clears `currentViewId`.

## `leads.page.html` — toolbar

Inline (no new component) — a saved-views menu component would be the second small component this step and pushes the file count over budget. The whole feature fits in ~60 lines of inline HTML.

UI:
- Trigger button (left of the advanced-filter button): "Views" with lucide `bookmark` icon. Shows current view name when one is active; "Default view" otherwise.
- Popover panel:
  - List of `savedViews()` — owned views first, then shared (small `users` icon next to shared).
  - Click → `applyView(v)`; the active view gets a checkmark.
  - "+ Save current as view…" link at the bottom (opens the mini-modal).
  - When a view is active and caller owns it: "Update this view" + "Delete this view" links above the divider.

Mini-modal "Save view":
- Name input (max 80).
- "Share with team" checkbox (only enabled if caller has any team-visibility — keep simple: always enabled; the backend trusts the choice).
- Cancel / Save.

## `lead-scoring-rules.page.ts` — Settings → Lead Scoring

Standalone Angular component, inline template (~180 LOC). Route: `/user/settings/lead-scoring`.

UI:
- Header: "Lead scoring rules — points add up across active rules; capped at 100."
- Table of rules: Name · Condition (human-readable, e.g. `status = qualified AND budget ≥ 50000`) · Points · Active · Actions.
- "+ Add rule" button → opens a rule-editor inline using the same `advanced-filter-modal` component from Step 6 as the condition picker (re-use, not duplicate). Extra fields above: Name, Points (numeric input with `min=-100 max=100`).
- Edit / Delete row actions.
- A small "Recompute scores now" button on the page header → calls the existing `POST /leads/scoring-rules/recompute` (add in this step if not present from Step 5 — single-line endpoint).

Permission gate: only visible to users with `leads.scoring.manage` (Owner by default; Admin if granted). For others, navigating to the URL returns a permission denied page.

## `user.routes.ts` — add route

Add inside the existing `'settings'` route children block:

```typescript
{
  path: 'settings/lead-scoring',
  loadComponent: () => import('./core/settings/lead-scoring-rules.page').then(m => m.LeadScoringRulesPage),
  canActivate: [permissionGuard('leads.scoring.manage')],
},
```

Sidebar registration: settings tabs are registered via the existing tab registry in `settings/tabs/`. Add a "Lead scoring" tab entry there *only if the registry currently iterates a list* — if so, one extra line. If not (each tab is hardcoded), surface from the Settings home page as a card link. Verify at implementation time; do not add a new tab system.

## Test `test_saved_views.py`

1. Create view (owner) → 200; appears in `list()`.
2. Duplicate (`owner_user_id`, `entity`, `name`) → 409.
3. Update by non-owner → 403.
4. Shared view appears in another user's `list()` within the same org.
5. Cross-tenant user does not see the shared view.
6. Delete by non-owner → 403; by owner → 204; subsequent `list()` omits it.
7. `config` payload validates: bad shape → 422 (only the type validator; semantic validation lives at the leads page).

## Acceptance

1. On `/user/leads`, open the Views menu → empty initially.
2. Apply advanced filter `status = qualified AND lead_score >= 50` + sort `lead_score desc` + hide Created column → "Save current as view…" → name "Hot qualified" → toggle share OFF → save.
3. Refresh page → "Hot qualified" appears in Views menu → click → all settings restored.
4. Toggle the view's "Share with team" ON via "Update this view" — another rep in the same org sees it.
5. Non-owner tries to update / delete a shared view → action buttons hidden; direct API call → 403.
6. Owner edits the view (e.g. add column Budget) → "Update this view" → reload restores the new config.
7. `/user/settings/lead-scoring` — Owner sees rule list. Add rule "Qualified + Mumbai" = `status eq qualified AND custom_data.city eq Mumbai`, points 25 → save → leads matching gain 25 points after next write (or immediately via "Recompute scores now").
8. Junior sales rep navigating to `/user/settings/lead-scoring` → permission denied.
9. Owner deletes a rule → confirm dialog → row gone → org-wide recompute kicked off.

## Lucide icons used

`bookmark`, `bookmark-check`, `users`, `pencil`, `trash-2`, `plus`. Verify all registered.

## Self-check vs the 10 rules

- ✅ Rule 1 — `core/saved_views` and `core/settings/lead-scoring` never touch packs.
- ✅ Rule 2 — `saved_views` has `org_id` + RLS from day one.
- ✅ Rule 5 — saved-views menu and lead-scoring page are inside existing module routes; the settings-tab registry is reused.
- ✅ Rule 6 — `saved_views.use` registered; `leads.scoring.manage` already registered in Step 5.
- ✅ Rule 7 — `pack.yaml` untouched.
- ⚠️ Rule 8 — 12 files. Slightly over the ~10 soft target but defensible: 7 are the new `saved_views` module (one per standard pattern file). If implementation drift pushes past 14 files / 400 LOC, split the lead-scoring settings page out as Step 7b mid-stream per Rule 9.
- ✅ Rule 9 — stop-and-report after this step; this is the final step in the track.
- ✅ Rule 10 — no TODOs; recompute on rule edits ships wired.

## Stop-and-report template

> ✅ Step 7 complete. **Leads update track complete.**
> **Files changed:** 12 (1 migration, 6 new saved_views backend incl. test, 1 modified main.py, 2 new FE, 3 modified FE).
> **What you can verify (smoke on Ajay's Workspace):**
> 1. Build + apply a complex filter, save as view, reload → view reapplies cleanly.
> 2. Share a view → another rep in the org sees it; cross-tenant rep doesn't.
> 3. Non-owner can apply a shared view but can't update/delete it.
> 4. Settings → Lead Scoring lists rules; add/edit/delete works; recompute runs.
> 5. Junior sales rep blocked from /settings/lead-scoring.
> **Tests added:** `test_saved_views.py` (7). Lead-scoring engine tests live in Step 5.
> **Raw INSERT SQL** for seeding a default "Hot Qualified" shared view on Ajay's Workspace:
> ```sql
> INSERT INTO saved_views (org_id, owner_user_id, entity, name, config, shared)
> VALUES (
>   '41f9ede9-41b3-44ce-b489-3004566d4068',
>   '<ajay-user-id>',
>   'leads',
>   'Hot Qualified',
>   '{"filter":{"all":[{"field":"status","op":"eq","value":"qualified"},{"field":"lead_score","op":"gte","value":50}]},"sort":"lead_score","order":"desc","view":"list"}',
>   true
> );
> ```
> **Self-check:** all 10 rules ✅ (Rule 8 noted at upper bound).
> **Leads track complete.** Pattern (`saved_views` + filter DSL + cursor pagination + column prefs) now reusable across `update-walkins-page/`, `update-contacts-page/` v2, and `tasks-page/`.
