# Step 8 — Dashboard refresh

**Goal:** Match AIXO's dashboard: greeting header + date-range pill, signature strip, KPI cards, revenue trend + funnel split, ops KPIs, follow-ups + appointments split, recent-activity card.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 6

---

## AIXO layout (in order top→bottom, single column max-w-1180)

1. **Greeting header** — flex row, wrap. Left: h1 `font-display` 700 26px `"{greeting}, {firstName}"`, sub `"Here's what's moving in your {workspaceCategory} workspace."` 14px text-muted. Right: date-range pill (7d / 30d / 90d / MTD) — segmented, `bg-surface` `border-subtle` `rounded-lg`, buttons `font-mono` 12px, active = `bg-accent-soft` `text-accent`.

2. **Signature strip card** — `bg-surface` `border-subtle` `rounded-2xl` 14px, p-5, `mb-5`, relative, overflow-hidden. Absolute inset-0 gradient overlay `linear-gradient(120deg, var(--accent-soft), transparent 55%)`. Header row: dot + title (font-display 600 15px) + `Live · updated {n}m ago` (mono 12px text-faint) right. Body: horizontal row of 5 stage cards (min-w-150 each, gap-3, flex-1). Each stage card: `bg-app` `border-subtle` `rounded-xl` 11px, p-3. Content: colored dot 7×7 + stage label 12.5px muted → count (mono 22px 600) → sub 11.5px text-faint → progress bar 3px h, filled with stage color, pct width.

3. **KPI grid** — CSS grid, `auto-fit minmax(210px, 1fr)`, gap-3.5, mb-5. Each KPI: `bg-surface` `border-subtle` `rounded-xl` 12px, p-4. Structure: label 12.5px muted → value (mono 26px 600 `letter-spacing: -.02em`) → row (trend mono 12px 600 in trend-color + "vs prev period" 11.5px faint).

4. **Revenue + Funnel split** — 2-col grid `minmax(300px, 1fr)`. Left card: chart title + toggle (Revenue / Leads chips), 190px chart canvas. Right card: title + funnel rows (each row: label + count + progress bar with `bg-accent` `opacity: pct`).

5. **Ops KPIs** — `auto-fit minmax(210px, 1fr)` grid. Cards: mono 26px value → 12.5px muted label.

6. **Follow-ups + Appointments split** — 2-col grid. Each is a card. Follow-ups card: header (title + count badge + Filters button + View all →) → tab chips → search input placeholder → empty state (calendar SVG + line + Add-task button). Appointments card: header + tab chips (Today / Upcoming) → empty state ("No appointments scheduled" + Schedule-one link).

7. **Recent activity card** — full-width card with header + empty text or list.

## Scope

Rebuild [`dashboard.page.html`](../../APP/src/app/features/user/core/dashboard/dashboard.page.html) and [`dashboard.page.ts`](../../APP/src/app/features/user/core/dashboard/dashboard.page.ts) with the layout above. Preserve every existing:
- Signal / observable / service injection (`DashboardService`, `KpiService`, etc.).
- Filter / date-range state (rename storage keys only if the new pill uses different values).
- Widget wiring under [`dashboard/widgets/`](../../APP/src/app/features/user/core/dashboard/widgets/) — restyle each widget component to the new card look.

If widgets are separate components, restyle each; do not merge them into one file.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/dashboard/dashboard.page.html` | modified — new layout |
| `APP/src/app/features/user/core/dashboard/dashboard.page.ts` | modified — expose greeting, dateRange signal |
| `APP/src/app/features/user/core/dashboard/widgets/*.{ts,html}` | modified — restyle each widget |
| `APP/src/app/features/user/core/dashboard/shared/*.{ts,html}` | modified — restyle |

**~8–10 files (split into two commits if it exceeds 10).**

## Verification

- Dashboard renders in dark + light with the exact AIXO structure.
- Date-range pill switches the underlying data source (existing behavior).
- Widgets that fetch data show loading skeletons in the new card frame (skeleton restyle deferred to a polish sub-step if needed).
- Empty states show the AIXO empty-state layout.

## Out of scope

- Adding new widgets or KPIs.
- Changing data fetching or query params.
