# Step 4 — Frontend: 3 new KPI cards + card→widget filter wiring

**Goal:** Add **Pending today · Completed today · Overdue** KPI
cards to the dashboard summary; clicking any card scrolls to the
widget and applies the matching bucket filter.
**Status:** COMPLETED
**Depends on:** Step 2 (endpoint returns the 4 counts) + Step 3
(widget exists to filter).

---

## Scope

### Backend — extend the existing summary payload

The three counts are already returned by `/dashboard/followups`
(Step 2's `counts` object). Rather than duplicate the aggregate
queries, `/dashboard/summary` calls the same DAL helper and inlines
the counts as cards.

Three new card entries in `_assemble_org_cards()` +
`_assemble_personal_cards()`:

- `key = 'followups.pending_today'` — format `number`, link = null
  (link is handled by the frontend anchor scroll — not a route).
- `key = 'followups.completed_today'` — format `number`, link = null.
- `key = 'followups.overdue'` — format `number`, link = null.

Delta pills disabled for these three (period-over-period doesn't
make sense for same-day snapshot metrics — comparing today's pending
count to yesterday's is confusing).

### Frontend — hero-strip reshuffle

Personal scope's hero swaps:

- **Before:** My tasks · My leads · My appointments · My conversion
- **After:** My tasks · **Pending today** · My appointments · My leads

`conversion.my_rate` moves to the secondary card row. Rationale
locked in the README: the daily-driver number matters more in the
hero than a lagging conversion metric.

Org scope's hero stays as-is (Pipeline value · Leads new today ·
Appointments today · Conversion rate). The three new cards land in
the secondary grid, ordered: pending → completed → overdue.

### Card → widget bucket wiring

Each new card gets a click handler in `dashboard.page.ts`:

```ts
onCardClick(card: DashboardCard): void {
  if (card.key === 'followups.pending_today') this.followupsWidget.setBucket('pending');
  else if (card.key === 'followups.completed_today') this.followupsWidget.setBucket('completed_today');
  else if (card.key === 'followups.overdue') this.followupsWidget.setBucket('overdue');
  else if (card.link) this.router.navigateByUrl(card.link);
  document.getElementById('todays-followups-widget')?.scrollIntoView({ behavior: 'smooth' });
}
```

The widget exposes `setBucket(bucket)` via a template ref bound in
`dashboard.page.html`.

Existing cards with `link != null` keep their current navigation
behavior — only the follow-up cards use the scroll+filter path.

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/dashboard/service.py` | EDIT — add 3 cards to org + personal assemblers |
| `APP/src/app/features/user/core/dashboard/dashboard.page.ts` | EDIT — hero-strip reshuffle + card→widget click handler + template ref |
| `APP/src/app/features/user/core/dashboard/dashboard.page.html` | EDIT — bind click, add anchor id on widget |

**~3 files, ~180 lines.**

---

## Verify

- Owner sees 3 new cards in the secondary grid.
- Employee sees hero re-ordered (Pending today replaces My
  conversion); Pending today · Completed today · Overdue in
  secondary.
- Clicking **Pending today** card scrolls the page to the widget +
  applies `bucket=pending` filter.
- Clicking **Overdue** card same behavior with `bucket=overdue`.
- Clicking any pre-existing card (e.g. "Leads new today") still
  navigates via its `link` — no regression.
- Delta pills do NOT appear on the 3 new cards.

---

## Self-check

Rule 5 — new cards register through the same card-format registry;
no per-card component. Rule 8 — 3 files, ~180 lines. Rule 10 — no
TODOs.

Prettier passes.

Stop-report + wait for "proceed" before Step 5.
