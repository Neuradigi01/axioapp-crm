# Step 7 — Automations list UI

**Goal:** Angular page at `/user/automations` listing all triggers in the org — name, event, channel, template name, enabled toggle, runs in last 7 days, last fired timestamp, actions. Sidebar entry registered. First frontend step in this track.
**Status:** COMPLETED — NEW `core/automation/module.py` exposes the `MODULE = ModuleDescriptor(id='automations', name='Automations', icon='workflow', layer='core', route='/api/v1/automations', frontend_route='/user/automations', permissions=ALL_KEYS, menu_position=260)` — the discovery walker in `core.module_registry.discover_modules` picks it up at lifespan start. `menu_position=260` slots "Automations" between Templates (250) and Settings (600+) — the logical adjacency the manager spec'd. NEW `automations-api.service.ts` typed wrapper for the 9 Step-3 endpoints: `list / get / create / update / enable / disable / delete / listRuns / listEventTypes`. Wire shapes (`TriggerRead`, `RunRead`, `EventCatalogEntry`, list-response envelopes, query DTOs) mirror the Pydantic schemas verbatim. NEW `event-type-chip.component.{ts,html}` — small dumb component that maps every event_type prefix (`user.* / lead.* / contact.* / appointment.* / quote.* / invoice.* / time.*`) to a Lucide icon + tailwind palette + human label, with the raw event_type in the `title` attribute for the hover. Mirrors the `channel-chip` from the templates module. Falls through to a neutral zinc chip with the `zap` icon for any unrecognised prefix so a future event still renders cleanly. NEW `automations.page.{ts,html}` — list page with header + filter bar + table. Filters: search (300ms debounced, hits the `q` query param), event-type dropdown (populated from `GET /event-types` at mount; falls back to empty cleanly if the call errors), channel dropdown (7 channels — whatsapp / email / sms / facebook / instagram / push), enabled toggle (All / Enabled / Disabled). Table columns: name (links to `/user/automations/:id` — Step 8 wires the editor), event-type chip, channel chip (reuses the templates `ChannelChipComponent`), delay (formatted as Immediate / Xs / Xm / Xh / Xd inline), updated_at, inline enable/disable toggle (custom Tailwind switch using a checkbox + peer-checked styling — disabled while in flight via the `togglingIds` Set so double-clicks can't race), Edit action link. Pagination at 25 per page with server-side `limit`/`offset`. Empty state surfaces a `workflow` icon + a hint about the two seeded triggers. Inline toggle uses optimistic local update — patches `items()` immediately on response without a full reload; error rolls back via the `loadError` banner. `canWrite()` computed signal hides the "New automation" header CTA + disables every row's toggle for read-only Employees (server permission gate still fires server-side as the suspenders to the UI's belt). Lazy route added under `/user/automations` gated on `permissionGuard('automations.read')`. 8 Lucide icons used (`workflow / plus / search / x / pencil / chevron-left / chevron-right / target / user-plus / users / calendar / receipt / clock / zap`) — all already in `app.config.ts`'s registered + provided lists, audited per `feedback_lucide_icon_registry.md` (the registry check passed without an edit). 3 Jasmine specs in `automations.page.spec.ts` (the project's test runner is Karma+Jasmine, not Jest — spec's "Jest" naming was loose): empty-state copy renders when API returns no rows; toggle on an enabled trigger calls `disable()` + flips the local row to `enabled=false`; channel-filter change re-fires `list()` with `channel='whatsapp'`. Spec run deferred per `feedback_pause_before_pytest.md` baseline.
**Depends on:** Step 3 (REST endpoints), Steps 5 + 6 (seeded triggers exist).

---

## Scope

In-scope:
- `core/automation/module.py`:
  - Module descriptor declaring sidebar position, icon (`workflow` Lucide), label ("Automations"), permission scope (`automations.read`), route `/user/automations`.
  - Registered with the existing core module registry.
- `APP/.../core/automations/automations-api.service.ts` — typed Angular HTTP client wrapping Step-3 endpoints. Retry-on-transient-failure interceptor per `feedback_http_retry_interceptor.md`.
- `APP/.../core/automations/automations.page.{ts,html}`:
  - Header: "Automations" title + "New automation" button (gated on `automations.write`).
  - Filter bar: event dropdown (populated from `/event-types` discovery endpoint), channel dropdown, enabled toggle, search input.
  - Table: name, event type chip, channel chip, template name (clickable → templates module), enabled toggle (inline), runs-7d count, last-fired timestamp, actions (Edit / Clone / Delete).
  - Empty state for fresh org: "Your automations will appear here. Welcome and Lead Confirmation are seeded by default."
  - Pagination: 25 per page.
- Reuses `template-status-badge` + `channel-chip` from `tasks/template-library/` Step 6 — no duplication.
- Lucide icons audited: `workflow`, `play`, `pause`, `copy`, `trash-2`, `clock`, `zap`.
- Route added to `APP/.../features/user/user.routes.ts` lazy-loaded + permission-gated.
- Jest smoke for list rendering + enable/disable toggle.

Out of scope:
- Trigger editor (Step 8).
- Run history detail (Step 9).
- "Run now" manual fire button — Step 9.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/module.py` | **NEW** |
| `APP/src/app/features/user/core/automations/automations-api.service.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/automations.page.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/automations.page.html` | **NEW** |
| `APP/src/app/features/user/core/automations/event-type-chip.component.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/event-type-chip.component.html` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — lazy route |
| `APP/src/app.config.ts` | edit — register Lucide icons |
| `APP/src/app/features/user/core/automations/automations.page.spec.ts` | **NEW** |

**~9 files. ~500 lines.**

## Plan

1. Module descriptor first — sidebar entry shows up.
2. API service.
3. Event-type chip — small dumb component.
4. Page shell with filter bar + table.
5. Inline enable/disable toggle calls the API + optimistic-updates the row.
6. Lucide audit — confirm icons present.
7. Jest: empty state, enable toggle, filter wiring.

## DB changes / migrations

None.

## Tests

3 Jest cases:
- Empty state visible when API returns no triggers.
- Toggling enabled calls `/enable` then refreshes.
- Filter changes re-fetch with the right query.

## Smoke

```
1. ng serve, log in.
2. Sidebar: "Automations" entry visible (Owner + Admin only).
3. /user/automations → list shows the two seeded triggers (User Welcome, Lead Confirmation).
4. Toggle one off → row re-renders.
5. Filter event=lead.created → only Lead Confirmation shows.
6. Click template name → navigates to /user/templates/{id}.
7. As Employee (no automations.read) → sidebar entry hidden + direct URL 403s.
```

## Risks

- Missing Lucide icons silently breaking the template (per memory). Audit before stop-report.
- Sidebar position vs existing entries — coordinate with the existing module registry; "Automations" sits next to "Templates" in the Settings group.

## Self-check (10 rules)

`features/user/core/automations/`. ✓ org_id via JWT. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar registered via registry. ✓ Permissions gate route + button. ✓ pack.yaml untouched. ✓ 9 files / ~500 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 7 — Automations list UI
Files: 9
Verify: sidebar entry visible; list shows seeded triggers; enable/disable inline; filters work.
Tests: 3 Jest cases.
Awaiting "proceed".
```
