# Step 19 — Accounts (auth) realignment

**Goal:** Realign the accounts pages (login, register, forgot / reset password, 2FA, verify-email, onboarding, accounts-layout) with the new AIXO tokens. They already use Tailwind (per prior migration) — this step swaps `bg-white` / `bg-zinc-900` / `border-zinc-200` for the new semantic tokens so both dark and light work consistently.
**Track:** Design Refresh — Track 5 (Auth + admin + polish)
**Status:** COMPLETED — 11 accounts HTML files bulk-swapped: accounts-layout, login, register, forgot-password, reset-password, two-factor, verify-email, email-verification-notice, onboarding. Existing tailwind auth pages now render with AIXO semantic tokens in both dark + light. Also swept `text-gray-*` / `border-gray-*` patterns (accounts pages use gray in places instead of zinc). `ng build` green.
**Depends on:** Steps 1, 2, 5

---

## AIXO patterns

### Accounts layout
- Full-viewport background `bg-app`. Centered card `max-w-md`, `bg-surface` `border-subtle` `rounded-2xl` p-8 `shadow-elevated`.
- Logo top (Core CRM wordmark, `font-display` 700, `text-default`). Optional 12px tagline `text-muted`.
- Bottom-right theme toggle (three-icon segmented, reused from Step 2).

### Forms inside cards
- Field wrapper from Step 5 (label + input + hint/error).
- Primary CTA full-width (`w-full`), 40px h, accent bg.
- Secondary link 13px `text-accent` centered below CTA (e.g. "Forgot password?").
- Divider "or" horizontal.
- Social buttons: 40px h, `bg-app` `border-subtle`, leading provider icon + "Continue with X".

### Captcha
- Existing captcha component styled to fit the card (border + rounded to match).

### Onboarding (multi-step signup completion)
- Full-page wizard, same step-ribbon pattern as Campaigns builder.
- Each step centered `max-w-lg` card.

## Scope

Every file under [`APP/src/app/features/accounts/`](../../APP/src/app/features/accounts/) — swap raw color/bg utilities for semantic tokens. Preserve every route, form control, validator, service call.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/accounts/accounts-layout/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/login/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/register/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/forgot-password/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/reset-password/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/two-factor/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/verify-email/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/email-verification-notice/*.{ts,html}` | modified |
| `APP/src/app/features/accounts/onboarding/**/*.{ts,html}` | modified |
| `APP/src/app/shared/captcha/*.{ts,html}` | modified — align border/bg with card |

**Group into 2 commits (auth pages / onboarding) to stay under 10 files each.**

## Verification

- Every accounts route renders in dark + light without regressions.
- All existing auth flows still work.
- Captcha visible and functional.

## Out of scope

- Any auth logic.
