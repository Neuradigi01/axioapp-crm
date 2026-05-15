# Step 2.5.4 — Org settings page

**Goal:** Build `/user/settings/org` — let an admin edit their org's name, currency, tax rate, timezone, and (DR.5-aligned) branding fields.
**Phase:** 2.5 — Core CRM Admin UI
**Status:** Pending
**Depends on:** DR.5 (per-org sidebar branding already exposes the `org_settings` shape).

---

## Scope

One Angular page + one form. Backend endpoints `GET /api/v1/settings` and `PATCH /api/v1/settings` already exist (Phase 2 — settings module).

## UI

Single page with a typed reactive form:

```
General
─────────
  Org name:        [Core CRM Demo                                ]
  Slug:            [core-demo]  (read-only — URLs depend on this)
  Pack:            core          (read-only)

Locale
─────────
  Currency:        [INR ▾]  (dropdown of supported ISO codes)
  Tax rate:        [0.00] %
  Timezone:        [Asia/Kolkata ▾]

Branding (DR.5)
─────────
  Display name:    [Core CRM Demo]   (sidebar header text)
  Logo:            [Upload]          (Phase 5 file-storage)
  Accent colour:   [#3366ff]

  [Save]
```

For 2.5.4 the **logo upload** is stubbed disabled (depends on Phase 5 file storage); the rest is functional.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/org/org-settings-page.component.ts` | created |
| `app/src/app/features/user/core/settings/org/org-settings-page.component.html` | created |
| `app/src/app/features/user/core/settings/org/org-settings.service.ts` | created — wraps `/api/v1/settings` |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — register `org` route + redirect default |
| `app/src/app/features/user/core/settings/settings-layout/` | minor — add Organization tab |

**5 files.**

## Permission gating

Page resolver checks `settings.read`. Edit/Save buttons require `settings.write`.

## Smoke

```
ng build --configuration development  # clean
# In browser as admin@core-demo.local:
#   - /user/settings/org → form pre-filled with Core CRM Demo / INR / 0% / Asia/Kolkata
#   - Change tax rate to 18.00 → save → toast success
#   - Refresh → 18.00 persists
#   - Login as employee@core-demo.local → /user/settings/org redirects (no settings.read)
```

## Backend tweak (if needed)

Currency / tax-rate are already in the `organizations` table from Phase 1.5. `PATCH /api/v1/settings` covers org-settings JSONB but may need to cover those core columns too — verify before starting. If it doesn't, add a small endpoint extension (1 file change in `core/settings/router.py`).

## Rollback

Delete 3 new files + revert 2 modified ones. No DB state change.
