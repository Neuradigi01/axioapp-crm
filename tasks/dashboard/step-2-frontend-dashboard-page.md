# Step 2 — Frontend dashboard page

**Goal:** Build `/user/dashboard` — the page that renders the cards + recent activity + upcoming appointments returned by Step 1's `GET /api/v1/dashboard/summary`. Generic renderer keyed on `card.format` so adding a card later is one backend change, no template edits.
**Track:** Dashboard
**Status:** Pending
**Depends on:** Step 1 (backend endpoint).

---

## Scope

One new page component under `app/src/app/features/user/core/dashboard/`, wired into `user.routes.ts` and reachable at `/user/dashboard`. The component fetches `/dashboard/summary` once on init, renders three sections (greeting + cards grid + activity feed + upcoming appointments). All cards rendered from a single template branch keyed on `card.format`.

## Layout

```
┌────────────────────────────────────────────────────────────────┐
│  Welcome back, Ajay                                            │
│  Owner · Ajay's Workspace                          [Refresh]   │
├────────────────────────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│ │ 7        │ │ ₹12.4L   │ │ 23       │ │ 4        │            │
│ │ New      │ │ Pipeline │ │ Open     │ │ Today's  │            │
│ │ leads    │ │ value    │ │ tasks    │ │ meetings │            │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐                         │
│ │ 89       │ │ 412      │ │ 42%      │                         │
│ │ Calls    │ │ Contacts │ │ Conv.    │                         │
│ │ this wk  │ │          │ │ rate     │                         │
│ └──────────┘ └──────────┘ └──────────┘                         │
├──────────────────────────────────┬─────────────────────────────┤
│ Recent activity                  │ Upcoming                    │
│ ─────────────                    │ ────────                    │
│ • Sarah created lead Anil K.     │ 2:00 PM Demo w/ Rajesh      │
│ • You scheduled Demo w/ Rajesh   │ 4:30 PM Site visit (M.A.)   │
│ • Ravi marked task complete      │ Tomorrow 10 AM ...          │
│ • ...                            │                             │
└──────────────────────────────────┴─────────────────────────────┘
```

Tailwind grid. Cards in a responsive `grid-cols-2 md:grid-cols-3 lg:grid-cols-4` layout. Two-column bottom split for activity + upcoming (stacks on mobile).

## Generic card rendering

The page renders any card the backend returns — no hardcoded card keys in the component. One template branch per `format`:

```html
@for (card of summary().cards; track card.key) {
  <a [routerLink]="card.link" class="kpi-card">
    <span class="value">
      @switch (card.format) {
        @case ('currency')  { {{ card.value | currencyFmt }} }
        @case ('percent')   { {{ card.value }}% }
        @case ('number')    { {{ card.value | number }} }
        @case ('text')      { {{ card.value }} }
        @default            { {{ card.value }} }
      }
    </span>
    <span class="label">{{ card.label }}</span>
  </a>
}
```

`currencyFmt` is a tiny inline pipe that defers to the org's currency code (already available via `FurnitureAuthService.currentOrg().currency` after `/me`). Falls back to `INR` if missing.

Cards without a `link` render as a div instead of `<a>`. The `top_performers` card has `format: 'leaderboard'` and gets a list-rendering branch (top 3 names + counts).

## Empty / loading states

- **Loading:** skeleton placeholders for cards + lists (Tailwind `animate-pulse`).
- **Error:** small banner at top: "Couldn't load your dashboard — [Retry]". Reuse the existing `extractApiError` util.
- **No recent activity:** "No recent activity yet — start a lead or schedule an appointment to see it here."
- **No upcoming appointments:** "No upcoming appointments. [Schedule one →]" linking to `/user/appointments`.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/dashboard/dashboard.page.ts` | created |
| `app/src/app/features/user/core/dashboard/dashboard.page.html` | created |
| `app/src/app/features/user/user.routes.ts` | modified — wire `/dashboard` route |
| `app/src/app/features/user/layout/welcome.component.ts` | (optional) modified — redirect `/user` empty path to `/user/dashboard` so the dashboard becomes the landing, replacing the placeholder welcome card; keep the welcome page only as a fallback for orgs with zero perms |

**3 files (4 with the welcome redirect). No backend.**

## Plan

1. Create the dashboard folder. Add `dashboard.page.ts` (standalone, OnPush) that:
   - Injects `HttpClient`, `FurnitureAuthService`, `Router`.
   - Loads `/api/v1/dashboard/summary` on init into a `summary = signal<DashboardSummary | null>(null)` and an `error = signal<string | null>(null)`.
   - Exposes `refresh()` that re-fetches.
   - Renders the template described above.
2. Add `dashboard.page.html` with the layout. Use `@if (summary(); as s)` to gate everything inside; skeleton loader otherwise.
3. Register the route in `user.routes.ts` under `path: 'dashboard'`. Lazy-load via `loadComponent`.
4. (Optional but recommended) Redirect the empty `/user` path to `/user/dashboard` so the dashboard is the landing page. Keep the welcome component only as a fallback if a future role legitimately has nothing to show.
5. Smoke against `ng serve` — log in as each demo role, see the cards differ.

## Tests

Angular tests deferred per project policy. Smoke is the gate.

## Smoke

```
ng build --configuration development                # clean build

# Manual via demo-logins pill:
# 1) Pick Core CRM — Owner   → /user/dashboard renders org-wide cards (8 cards).
# 2) Pick Core CRM — Admin   → same.
# 3) Pick Core CRM — Employee → personal cards (6 cards, my-prefixed labels).
# 4) Click any card → routes to /user/<module> with the right filter.
# 5) Refresh button → spinner → cards re-populate.
# 6) Disconnect network → reload → error banner with Retry button.
```

## Risks

- **Bundle-size regression** if the dashboard page imports the full Material library for its visuals. Mitigation: Tailwind-only (matches the new-page policy from CLAUDE.md). No Material imports in this component.
- **Stale data on long-running sessions.** The dashboard fetches once on mount. A user who leaves the tab open for hours sees stale numbers. v1 ships with a manual [Refresh] button. Auto-refresh-every-N-minutes is a v2 polish.
- **Card list breaks if backend adds a `format` the frontend doesn't know.** The `@default` branch renders the raw value as a fallback, so the page stays alive — but the card might look ugly. Treat any new format addition as needing a matching template branch.
- **Welcome-page redirect.** If we redirect `/user` → `/user/dashboard` and a future role legitimately has zero cards, that user lands on a blank dashboard. The empty-state copy on the dashboard handles this gracefully ("No recent activity yet — …"). Don't break the redirect.

## Rollback

Revert the 3–4 source files. Route disappears; users hitting `/user/dashboard` get the existing router 404. No data lost.
