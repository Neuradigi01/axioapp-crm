# Step 15 — Reviews + Reporting refresh

**Goal:** Restyle the Reviews module and Reporting (dashboards / saved reports) module.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### Reviews
- Page header + filter chips (channel: Google / Facebook / Yelp / All; rating: 5⭐/4⭐/…).
- List of review cards: header row = platform icon + star row (rendered with SVG stars, filled with `text-amber-400` for `<= rating`) + timestamp mono. Body = review text. Footer = customer name + reply button.
- Reply drawer / modal opens with a textarea + AI-suggest button.

### Reporting
- Landing page: report category cards (Sales / Marketing / Ops / Custom).
- Report detail: same as Dashboard shape — KPI row + charts + tables in a card grid.
- Date-range pill top-right.
- "Save as..." / "Schedule..." icon buttons.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/reviews/*/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/reporting/*/*.{ts,html}` | modified |

**~6–8 files.**

## Verification

- Both modules render correctly in dark + light.
- Stars render with proper colors.

## Out of scope

- Chart library changes.
- Backend report queries.
