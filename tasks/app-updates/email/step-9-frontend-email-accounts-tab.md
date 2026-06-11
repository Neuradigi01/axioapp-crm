# Step 9 — Frontend (Settings): Email Accounts tab — connect/disconnect + per-account dashboard

**Goal:** New Settings tab where every user manages their own connected mailbox(es), and Owners see a roll-up of all accounts in the org. Connect flow kicks the OAuth redirect; status, last sync, send count, and disconnect controls are visible per row.
**Track:** App Updates → Email
**Status:** Pending
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
