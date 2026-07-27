# Step 20 — Admin panel visual refresh

**Goal:** Apply AIXO tokens across the legacy admin panel so it visually matches the rest of the app. **Visual only** — no logic, routing, or feature changes.
**Track:** Design Refresh — Track 5 (Auth + admin + polish)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## Scope override

CLAUDE.md marks [`features/admin/`](../../APP/src/app/features/admin/) as untouched. This track has a scoped exception for **visual work only**, recorded in the `project_design_refresh_track.md` memory. After this step, admin remains untouched for functional changes.

## Approach

1. Do NOT rewrite admin templates from scratch. Instead:
   - Where admin uses Material (`mat-card`, `mat-table`, `mat-form-field`, `mat-menu`, `mat-dialog`), the token remap done in Step 1 + Material overrides in `styles.scss` (Steps 5 / 6 / 7) already inherit. In many cases, no admin-file edit is needed — the module simply looks better because its Material CSS variables now resolve to AIXO values.
   - Where admin uses raw color utilities (`bg-white`, `bg-gray-*`, `border-gray-*`), swap for semantic tokens.
   - Where admin has custom SCSS with hardcoded hex, swap for `var(--*)`.
2. Preserve every existing button, route, guard, form. Do not "modernize" behavior.
3. Test both dark and light modes.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/admin/**/*.html` | modified — color/bg class swaps only |
| `APP/src/app/features/admin/**/*.scss` | modified — hex → `var(--*)` swaps |

**Volume depends on the admin surface — split into 2–3 commits by admin sub-section (users / dashboard / settings) to stay under 10 files each.**

## Verification

- Every admin route renders in dark + light.
- No `bg-white` / hardcoded hex left in admin.
- All admin functions still work (spot-check: user list, role edit, one dialog).
- Login → "Admin login" button still routes to `/admin/dashboard`.

## Out of scope

- Any admin logic.
- Deleting or moving admin routes.
- Consolidating admin with `/user/settings/**`.
