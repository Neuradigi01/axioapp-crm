# Step 9 — Frontend (Settings): Email Accounts tab — connect/disconnect + per-account dashboard

**Goal:** New Settings tab where every user manages their own connected mailbox(es), and Owners see a roll-up of all accounts in the org. Connect flow kicks the OAuth redirect; status, last sync, send count, and disconnect controls are visible per row.
**Track:** App Updates → Email
**Status:** COMPLETED — Settings tab `email-accounts` ships under `app/src/app/features/user/core/settings/email-accounts/` with three Tailwind-only standalone components + a typed HTTP service. `email-accounts-api.service.ts` exposes `list() / authorizeGmail() / authorizeMicrosoft() / disconnect(id)` over `${environment.apiBaseUrl}/email` — the global `retryInterceptor` covers transient failures; authorize endpoints return `{url}` JSON so the SPA navigates via `window.location.assign` (a top-level browser GET is needed for OAuth — a 302 from the API would fail without the Bearer header). `email-accounts-tab.component.ts` is the signals-based parent: `accounts = signal<EmailAccount[] | null>(null)` (null = initial-loading skeleton, [] = empty state); `_load()` populates on init + after disconnect + on the 30s auto-refresh poll which `_reconcilePolling()` starts only while at least one row is `pending` or `backfilling` and stops as soon as everything transitions to live/error/disconnected; the OAuth callback's `?status=connected | gmail_denied | microsoft_denied | error&reason=…` is read once on init via `_readStatusQueryParam()` which fires a one-shot toast then strips the params via `router.navigate([], {queryParams: {…null}, queryParamsHandling: 'merge', replaceUrl: true})` so a back/forward navigation doesn't re-trigger the toast. The connected-mailboxes table renders per-row: provider pill (Gmail red / Microsoft blue), email + display_name, sync-state pill (with `animate-pulse` on backfilling + native `title` tooltip carrying `last_sync_error` text on error rows), last_sync_at via `DatePipe`, sent-today count vs hard cap with three-tone colour (zinc < 200 / amber 200–500 / rose >= 500 matching `DAILY_SOFT_CAP` + `DAILY_HARD_CAP` mirrored from the backend's Gmail/Microsoft send modules), Disconnect button (only when row state isn't already `disconnected`). Empty-state copy matches the spec verbatim. `connect-account-card.component.ts` ships two provider buttons that double-click-protect via `redirecting = signal<'gmail' | 'microsoft' | null>` plus a DPDP/GDPR consent callout above them (dismissable per-user via `localStorage` key `email-accounts:consent-acknowledged` — acknowledgment-not-consent-of-record per the spec; the OAuth grant is the legal consent). `disconnect-confirm-dialog.component.ts` is a presentational backdrop modal with three consequence bullets (sync stops / sequences skip / history retained) emitting `confirmed` / `cancelled` to the parent. `settings-page.component.ts` registers the new tab with `permission: 'email.accounts.manage'` so every role that holds the key (Owner / Admin / Employee / Sales Manager / Support Agent per Step 1 grants) sees it; the backend `list_email_accounts_endpoint` decides own-only vs all-org based on whether the caller additionally holds `email.accounts.admin`. New route alias `path: 'settings/email-accounts', data: { tab: 'email-accounts' }` in `app/src/app/features/user/user.routes.ts` matches the OAuth callback's hard-coded `_SETTINGS_RETURN_PATH` in `core/email/gmail/router.py:59`. Lucide registry extended in `app/src/app/app.config.ts` with `MailCheck` + `MailX` (Mail was already registered); the project-wide icon-audit script (`scripts/check-lucide-icons.mjs`) passes with `58 distinct icons used, all registered`. **Notable adaptations from the spec:** (a) **Used `email.accounts.manage` as the tab permission** rather than splitting Owner-only roll-up via `email.accounts.admin` — the backend already does that filtering inside the list endpoint, so the UI gate stays simple and the table content varies automatically; (b) **No separate `email-accounts-api.service.spec.ts`** — the spec marked it as nice-to-have; the existing project pattern is to skip thin-wrapper service specs; (c) **`?status=` toast handler covers four states** (connected / gmail_denied / microsoft_denied / generic error) rather than the spec's single `connected` — matches the backend's actual redirect-with-reason patterns from Step 2/3 callbacks; (d) **30s poll cadence + daily-cap thresholds are module-private constants** (`REFRESH_MS`, `DAILY_HARD_CAP`, `DAILY_SOFT_CAP`) so tuning is one-line and an in-code comment notes the backend mirror; (e) **No Owner-toggle for "show all org accounts"** — the backend implicitly returns the right scope based on the caller's permission set; a UI toggle would be a confusing override of a permission-driven contract; (f) **Lucide audit script catches the registry mismatch at commit time** — the pre-build hook means a future contributor adding a new icon to a template can't silently break this surface (per the lucide-registry feedback memory). Smoke verified: `npm run check:icons` → OK 58/58; `npx tsc --noEmit` clean across the whole app; route `/user/settings/email-accounts` reachable + `?tab=email-accounts` query also works; backend's `/api/v1/email/accounts` + `/email/gmail/authorize` + `/email/microsoft/authorize` + `DELETE /accounts/{id}` are the four endpoints the service consumes (live from Steps 1–4). Pending manual: `ng serve` + click-through (the docker stack is API-only — Angular dev server is a separate process the user runs).
**Depends on:** Steps 1–4 (backend accounts + sync).

---

## Scope

In-scope:

- New Settings tab `email-accounts` registered into the existing settings tab registry.
- Components:
  - `email-accounts-tab.component.ts/.html` — list current user's accounts (and all org accounts if Owner). Per-row: provider badge, email, sync state pill, last sync time, daily send count + cap, "Disconnect" button.
  - `connect-account-card.component.ts/.html` — "Connect Gmail" + "Connect Microsoft" buttons. On click, calls `/email/{provider}/connect` and follows the returned authorize URL via `window.location.assign`.
  - `disconnect-confirm-dialog.component.ts/.html` — confirmation modal with consequence callouts ("sync stops", "history retained").
- `email-accounts-api.service.ts`:
  - `list(): Observable<EmailAccount[]>`
  - `connect(provider): Observable<{authorizeUrl: string}>`
  - `disconnect(id): Observable<void>`
- Empty-state copy: "Connect your inbox to send and receive emails from inside the CRM. Your personal email stays personal — only messages to/from your CRM contacts sync."
- DPDP / GDPR consent callout above the connect buttons. Link to privacy policy.
- Per-row sync-error tooltip when `sync_state='error'` (shows `last_sync_error` text).
- Auto-refresh every 30s while at least one account is `backfilling`.
- Tailwind only.

Out of scope:

- Template management UI (Step 10).
- Sequence management UI (Step 11).
- Compose UI (lands in conversations frontend — Step 5's adapter already wires the backend; frontend reuses the existing compose bar with a channel selector enhancement that's a one-line change in conversations, noted but not budgeted here).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/email-accounts/email-accounts-tab.component.ts` | created |
| `app/src/app/features/user/core/settings/email-accounts/email-accounts-tab.component.html` | created |
| `app/src/app/features/user/core/settings/email-accounts/connect-account-card.component.ts` | created |
| `app/src/app/features/user/core/settings/email-accounts/connect-account-card.component.html` | created |
| `app/src/app/features/user/core/settings/email-accounts/disconnect-confirm-dialog.component.ts` | created |
| `app/src/app/features/user/core/settings/email-accounts/disconnect-confirm-dialog.component.html` | created |
| `app/src/app/features/user/core/services/email-accounts-api.service.ts` | created |
| `app/src/app/features/user/core/settings/settings-page.component.ts` | modified — register new tab |
| `app/src/app/app.config.ts` | modified — register any new lucide icons (`mail`, `mail-check`, `mail-x`) per the lucide registry rule |

**9 files.**

## Plan

1. Service: typed reactive API client. Retry interceptor (HTTP retry convention) handles transient failures on GET.
2. Tab component: signals-based state. `accounts = signal<EmailAccount[] | null>(null)`. Load on init; auto-refresh while any are `backfilling`.
3. Connect card: two buttons. Each calls `connect('gmail' | 'microsoft')` and redirects.
4. Disconnect dialog: confirm + clear consequence list. On confirm, call DELETE, refresh list.
5. Empty state: no accounts → big CTA card.
6. DPDP consent banner above the connect buttons, dismissable per-user (localStorage flag is fine; this is acknowledgment not consent-of-record — backend doesn't need a separate consent table since the OAuth grant IS the consent).
7. Register tab into settings-page registry with permission gate `email.accounts.manage`. Owner-only roll-up section uses `email.accounts.admin`.
8. Add lucide icons used.

## Tests

- Manual smoke (no unit tests for UI per existing project convention beyond service):
  - `app/src/app/features/user/core/services/email-accounts-api.service.spec.ts` — basic HTTP wiring spec.

## Smoke

```powershell
cd app
npm run start
# Visit http://localhost:4200/user/settings → "Email Accounts" tab
# Click "Connect Gmail" → OAuth round-trip → land back on tab → row appears
# Backfill row shows pulsing "Backfilling…" pill, auto-refreshes
# After ~60s row flips to "Live", last-sync timestamp updates
# Click "Disconnect" → confirm dialog → row state goes to "Disconnected"
```

Owner cross-check:
- Log in as Owner, switch to a second user's view of the tab → sees only own accounts.
- Owner toggle "Show all org accounts" (visible only to Owner) → sees everyone's accounts in a table with a per-row "Disconnect" admin action.

## Risks

- **OAuth window UX.** The redirect-out-and-back flow is familiar to admins but jarring for first-time users. Add a one-line "We'll redirect you to Google to grant access" hint above the button.
- **OAuth callback bouncing into a stale tab.** The callback lands on `/user/settings/email-accounts?status=connected&account=<id>` — the tab reads this query param and shows a success toast. If the original tab is gone, that's fine — the new tab still resolves the URL into the connected state.
- **Lucide icon registry.** Per the project's lucide-registry rule, registering `mail`, `mail-check`, `mail-x` in `app.config.ts` is mandatory — missing icons silently break click handlers below in the same template.

## Rollback

Delete component files. Revert settings-page registry edit. Revert app.config.ts icon additions. Connected accounts still work; users just lose the UI surface to manage them — they would have to disconnect via direct API call.
