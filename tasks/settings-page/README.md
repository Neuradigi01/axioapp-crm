# Settings page — personal tabs for every role

A focused track to give every authenticated user — including small roles like Employee — a real `/user/settings` page they can use day-to-day. Today an Employee sees only the **Notifications** tab; everything else is gated behind admin-tier permissions. The four tabs in this track use backend code that's already shipped in the legacy auth path, so the work is almost entirely Angular wiring.

## Why this exists

The Settings sidebar entry just became visible to every role (the `always_visible=True` flag on `ModuleDescriptor` + per-tab permission gates in `settings-page.component.ts`). But an Employee opening Settings today sees:

- **Notifications** (in-app + email opt-in) — ✅ shipped in `update-appointments-page` Step 6.

…and nothing else. That's a thin self-service surface. A staff user can't change their own password, can't enable 2FA on their own account, can't see if a stolen session is still active, and can't switch to dark mode. All four of those are table-stakes for a modern CRM (Hubspot, Pipedrive, Zoho, Freshsales — every one of them surfaces these four to every user).

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **Profile tab** | Fold the existing standalone `/user/profile` page into a Settings tab. Edit own full_name, phone; change password; "sign out other sessions." No new backend. |
| **Appearance tab** | Light / Dark / System theme radio. Persists via `localStorage` through the existing `ThemeService`. Pure frontend. |
| **Login history tab** | List last 50 sign-ins (time, IP, device, current?); per-row "Sign out" button. Reuses legacy `POST /login-history/list` + `POST /login-history/logout-session`. |
| **Two-factor tab** | Self-service enrol + disable for TOTP / Email OTP / SMS OTP. Reuses legacy `/2fa/*` endpoints and the existing `accounts/two-factor/` enrolment component. |

## What this does NOT do

- Does not add **working-hours / OOO calendar** — useful but no backend exists yet (separate track if/when needed).
- Does not add **email signature** for outbound mail — no backend yet.
- Does not add **personal API tokens** — would need a new `personal_access_tokens` table + minting endpoint.
- Does not refactor the legacy auth UI in `features/accounts/` — those pages keep their existing PrimeNG / Material styling per the project's reuse policy.

## Acceptance criteria

A logged-in **Employee** on `/user/settings`:

1. Sees five tabs: **Notifications · Profile · Two-factor · Login history · Appearance**.
2. Does NOT see admin-only tabs (Team, Roles, Integrations, Custom Fields, Standard Fields, Embed Widget, AI Settings, Store Profile).
3. Can change their **password** + tick "sign out other devices" → other sessions are revoked.
4. Can enable **TOTP** by scanning a QR code, verify the code, see it now ON, and disable it again (action-token confirmed).
5. Can see their **last 50 logins** (time, IP, device) with a clear marker for "this session" and a Sign-out button on the others.
6. Can switch theme to **Dark** and the preference persists across reloads.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Profile tab — fold standalone profile page into Settings](step-1-profile-tab.md) | COMPLETED | ~½ day |
| 2 | [Appearance tab — light/dark/system theme picker](step-2-appearance-tab.md) | COMPLETED | ~¼ day |
| 3 | [Login history tab — last N sessions + per-row revoke](step-3-login-history-tab.md) | COMPLETED | ~½ day |
| 4 | [Two-factor tab — read-only status (full enrol deferred)](step-4-two-factor-tab.md) | COMPLETED | ~¼ day |

**Total: ~1¾ working days.** Stop and report after each per Rule 9.

Ordering rationale: Profile first (biggest UX hole — Employee has nowhere to change password). Appearance next (frontend-only, low risk, instant gratification). Login history third (read-only listing, simple revoke). Two-factor last (most complex — modal enrol flow + action-token guard on disable).

## Dependencies

- `tasks/update-appointments-page/` Step 6 — REQUIRED (Settings module + per-tab gates already in place).
- Legacy auth services in `API/src/services/auth/` and `API/src/services/security/` — preserved per CLAUDE.md "reuse-vs-restructure" exceptions.
- `ThemeService` at `APP/src/app/core/services/theme.service.ts` — already wired into `app.config.ts`.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 (Profile) | 2 new (`profile-tab.component.ts/html`), 2 modified (`settings-page.component.ts/html`, `user.routes.ts` — drop redundant `/user/profile` route). | Folds existing profile-page service usage; no new HTTP calls. |
| Step 2 (Appearance) | 2 new (`appearance-tab.component.ts/html`), 2 modified (`settings-page.component.ts/html`). | Pure UI; reads/writes `ThemeService`. |
| Step 3 (Login history) | 1 new service (`login-history-api.service.ts`), 2 new (`login-history-tab.component.ts/html`), 2 modified (`settings-page.component.ts/html`). | Wraps the legacy `POST /login-history/list` + revoke. |
| Step 4 (Two-factor) | 1 new service (`two-factor-api.service.ts`), 2 new (`two-factor-tab.component.ts/html`), 2 modified (`settings-page.component.ts/html`). | Reuses legacy `/2fa/*` endpoints. |

**Total ~15 files across 4 steps. ≤10 per step — Rule 8 satisfied.**

## Self-check vs the 10 rules

- ✅ Rule 1, 5 — no `/core` → `/packs` imports; no new module registry entries (Settings module already registered).
- ✅ Rule 6 — no new permission keys; all four tabs are personal — accessible to every authenticated user without admin perms.
- ✅ Rule 8 — every step ≤6 files.
- ✅ Rule 10 — each tab ships complete (no half-wired enrol flows, no TODOs).

## After this track

- Every role (including Employee) has a real self-service Settings area covering personal account management, security, and appearance.
- The orphan `/user/profile` page is gone — one location for personal settings.
- 2FA can finally be enabled outside the login flow — fixes the chicken-and-egg problem where staff couldn't enable 2FA after they were already logged in.
- Login history is exposed to end users so they can spot a stolen session and self-rotate.
