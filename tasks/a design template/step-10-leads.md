# Step 10 — Leads refresh

**Goal:** Restyle the Leads list view AND the pipeline (Kanban) board view.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7, 9

---

## AIXO patterns to apply

### List view
- Same table pattern as Contacts (Step 9).
- Leads-specific columns: name / contact / source / stage / value / owner / next-action. Stage cell uses a colored dot + label; value cell uses `font-mono`.

### Pipeline (Kanban) board
- Horizontal scroll of columns; each column 300–320px wide.
- Column header: 12px 600 uppercase `letter-spacing: .06em` `text-muted` label + `font-mono` 12px `bg-accent-soft text-accent` count badge on the right.
- Column body: `bg-surface-2`, `rounded-xl` 12px, p-3, gap-2 flex-column of lead cards.
- Lead card: `bg-surface` `border-subtle` `rounded-xl`, p-3. Structure: title (14px 600) → contact chip → value (mono 13px) → tag chips → footer with owner-avatar + last-activity (`font-mono` 11px text-faint).
- Drag ghost: card with `shadow-elevated` and slight scale + opacity.
- Empty column: single line "Drop leads here" text-faint 12.5px, centered vertically.
- **Toggle** between list ↔ board lives in the page header as a two-button segmented control.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/leads/leads-list/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/leads/leads-pipeline/*.{ts,html,scss}` | modified |
| `APP/src/app/features/user/core/leads/lead-detail/*.{ts,html}` | modified (side drawer, same pattern as Contacts) |
| `APP/src/app/features/user/core/leads/lead-form/*.{ts,html}` | modified |

**~8–10 files.**

## Verification

- List → board toggle works, both views styled correctly, drag-drop still functional.
- Lead detail drawer matches Contacts drawer shape.
- Empty pipeline column shows AIXO empty look.

## Out of scope

- Kanban drag-drop logic.
- Column CRUD (rename / add / delete stages) — pipelines module handles that.
