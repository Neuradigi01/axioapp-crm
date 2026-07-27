# Step 6 — Cards + tables + chips + badges + empty states

**Goal:** Restyle the shared card, table, chip, badge, page-header, and empty-state primitives.
**Track:** Design Refresh — Track 3 (Shared primitives)
**Status:** Pending
**Depends on:** Step 1

---

## AIXO reference

### Card
- `bg-surface`, `border-subtle` (1px), `rounded-xl` (12px) or `rounded-2xl` (14px), `p-4` to `p-6` depending on density.
- Card header: title (`font-display` 600 14.5px) + optional action button (accent link `View all →`).
- Optional accent gradient overlay for "signature" cards (dashboard signature strip): `background: linear-gradient(120deg, var(--accent-soft), transparent 55%)` on an absolute-positioned inset-0 layer, pointer-events-none.

### Table
- No horizontal stripes. Rows separated by 1px `border-subtle` bottom.
- Header row: `bg-surface-2` (or transparent + slight `text-muted` uppercase 11px labels).
- Row height ~52px. Hover `bg-surface-2`. Cell padding 12px 16px.
- Checkbox column 40px. Row-hover action buttons on the right (icon-only, `text-faint`, hover `text-default`).

### Chip / badge
- **Chip (filter):** pill, `bg-surface-2`, `border-subtle`, `text-muted`, 12.5px, 5px 11px padding. Active chip: `bg-accent-soft`, `text-accent`, no border.
- **Badge (count):** `font-mono` 11px, `bg-accent-soft` `text-accent`, 1px 7px padding, `rounded-full`.
- **Status pill:** 12px, `rounded-full`, 1px 8px padding. Success `bg-emerald-500/10 text-emerald-400`, warn `bg-amber-500/10 text-amber-400`, danger `bg-red-500/10 text-red-400`, neutral `bg-surface-2 text-muted`. (These are semantic per-status color tokens; add to Tailwind as `bg-status-success/soft` etc. — optional.)

### Empty state
- Centered content, 26px vertical padding.
- Icon: 34px stroke SVG, `stroke: var(--text-faint)`, stroke-width 1.6.
- Line 1: 14px 600.
- Line 2 (optional): 13px `text-muted`.
- Primary CTA button (from Step 5), gap 12px from lines above.

### Page header
- Container: flex, align-items:flex-end, justify-between, gap 16px, flex-wrap, mb-6.
- Title: h1 `font-display` 700 26px `letter-spacing: -.02em`.
- Subtitle: 14px `text-muted` `mt-1`.
- Right side: contextual actions (date pill / filter / primary CTA).

## Scope

1. Restyle any shared `AppCard` / `AppTable` component (or if not present, document the utility-class recipes).
2. Restyle Material `.mat-mdc-card` overrides in `styles.scss` to match the AIXO card.
3. Restyle Material `.mat-mdc-table` if used, or the raw `<table class="page-layout__table">` styles.
4. Add a `.chip`, `.chip-active`, `.badge`, `.status-*` layer to `aixo-components.scss`.
5. Add or restyle an `AppEmptyState` shared component under `core/shared/`.
6. Add or restyle an `AppPageHeader` shared component under `core/shared/`.

## Files to touch

| File | Action |
|---|---|
| `APP/src/styles.scss` | modified — `.mat-mdc-card`, `.page-layout__table` overrides |
| `APP/src/styles/aixo-components.scss` | modified — chip/badge/status classes |
| `APP/src/app/features/user/core/shared/empty-state/empty-state.component.{ts,html}` | created or modified |
| `APP/src/app/features/user/core/shared/page-header/page-header.component.{ts,html}` | created or modified |

**~4–6 files.**

## Verification

- Contacts list (Step 9) previews as the new table look.
- Dashboard KPI cards (Step 8) preview as the new card look.
- Empty state on Reviews with no data shows the new look.

## Out of scope

- Actual dashboard/list-page rewrites — Steps 8+.
