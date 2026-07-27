# Step 21 — Error + Access Denied + shared micro-pages

**Goal:** Restyle the small non-feature pages: 404 / error page, `/user/access-denied` (from RBAC track), and any other "meta" pages (maintenance, coming-soon).
**Track:** Design Refresh — Track 5 (Auth + admin + polish)
**Status:** COMPLETED — 1 file swept: `access-denied.page.html`. No separate `error/` folder exists in this repo (404 handling is routed elsewhere / falls back to router default). Access-denied page now uses AIXO semantic tokens with shield/lock icon layout. `ng build` green.
**Depends on:** Steps 1, 5

---

## AIXO patterns

### Error / not-found page
- Full-page centered content.
- Big glyph: `font-display` 96px accent-soft "404" or a stroked SVG icon.
- Line 1: `font-display` 600 20px "Page not found".
- Line 2: 14px text-muted (helpful description).
- Primary button "Go home" (accent) + secondary "Go back" (border).

### Access denied
- Same layout, different icon (shield / lock).
- Message references the required permission (existing text).
- Primary "Back to dashboard" + secondary "Contact your admin".

### Coming soon / maintenance
- Same layout, icon = clock or wrench.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/error/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/access-denied/*.{ts,html}` | modified |
| Any other meta pages under `/user/core/` | modified as found |

**~3–5 files.**

## Verification

- Trigger a 404 → correct look.
- Log in as an Employee → open Owner-only URL → access denied renders with new look.

## Out of scope

- Error boundary behavior.
- Access-denied logic (RBAC).
