# Step 7 — Frontend (Settings): Integrations page — connect/disconnect + form/campaign picker

**Goal:** Build `/user/settings/integrations` — a top-level Settings tab showing provider cards (Google Ads, Meta Ads), each with Connect/Disconnect buttons, post-connect Account info, Pages/Campaigns/Forms tree, per-form Subscribe toggle, webhook URL display (Google) or one-click subscription (Meta), and a "Re-connect required" warning when a token expires.
**Track:** Ad Integrations
**Status:** Pending
**Depends on:** Steps 1–5 (backend complete enough to expose connect/disconnect + list pages/forms + subscribe).

---

## Scope

In-scope:

- New route `/user/settings/integrations` registered with the Settings tab registry.
- `IntegrationsPageComponent` renders two provider cards.

  **Google Ads card:**
  - Not connected: button "Connect Google Ads" → navigates to `/api/v1/integrations/google/authorize` (which 302s to Google consent).
  - After redirect-back: shows connected status, account email.
  - "Accounts" section: list of accessible Google Ads accounts; click expands per-account list of Lead Forms.
  - Per form row: "Subscribe" toggle (creates `integration_subscriptions` row if on; soft-deletes if off).
  - Webhook URL display: `https://api.furnicrm.app/api/v1/integrations/google/webhook/v1/{webhook_secret}` (or local equivalent) with copy button and instructions: "Paste this into your Google Ads Lead Form's webhook URL field."
  - "Re-connect" button if status is `expired`.
  - "Disconnect" button with confirm modal — calls `DELETE /api/v1/integrations/google` (the generic `/integrations/{provider}` endpoint from Step 1).

  **Meta Ads card:**
  - Not connected: button "Connect Facebook / Instagram" → 302 to Meta consent.
  - After redirect-back: shows connected status, Facebook user name.
  - "Pages" section: list of Pages the user manages; expand per-Page to show lead-gen forms.
  - Per form row: "Subscribe" toggle. The backend ensures the Page is subscribed automatically when the first form on it gets toggled on; unsubscribes when the last toggles off.
  - "Token expires on YYYY-MM-DD (X days from now)" reminder; "Re-connect" CTA when within 7 days.
  - "Disconnect" button.

- DLQ summary card at the bottom: "X webhook deliveries failed and need attention" with a link to a DLQ page (Step 8 introduces the full DLQ UI; here, just the count + link suffices — link can route to Step 8's page when built, or to a placeholder for now).

- `integrations-api.service.ts` — typed wrappers for all admin endpoints.

Out of scope:

- Field mapping editor — Step 8.
- DLQ detail / replay UI — Step 8.
- Multi-account per provider (advanced).
- Routing config UI — Step 8 has it as part of the integrations status panel.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/integrations/integrations-page.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/integrations-page.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/integrations-api.service.ts` | created |
| `app/src/app/features/user/core/settings/integrations/google-card.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/google-card.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/meta-card.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/meta-card.component.html` | created |
| `app/src/app/features/user/core/settings/settings.routes.ts` | modified — register the route + tab |

**8 files.** At rule-8 ceiling — split provider cards into their own files for testability.

## Plan

1. Generate `integrations-api.service.ts` covering: `list()`, `disconnect(provider)`, `getGoogleAccounts()`, `getGoogleForms(customerId)`, `subscribeForm({integrationId, externalFormId, externalFormLabel})`, `unsubscribeForm(subId)`, `getMetaPages()`, `getMetaForms(pageId)`, `getDlqCount()`.
2. `IntegrationsPageComponent` loads `list()` on init; resolves which provider cards show "connected" vs. "not connected".
3. Each card is its own standalone component with its own signals for `accounts/pages/forms`, click handlers, toggle handlers. Component receives the `Integration | null` row as an `@Input()`.
4. Connect button = anchor with `href` to the authorize endpoint. The endpoint requires admin JWT — use a small helper that opens the URL with the bearer token as a one-time query param OR uses `fetch` with credentials and then a `window.location.assign` on success. Match the existing project's OAuth init pattern.
5. After Google's redirect lands back at `/user/settings/integrations?status=google_connected`, the page reads the query param + shows a toast + refetches `list()`.
6. Webhook URL display: read from the backend (`integrations.list()` returns `webhook_url` already constructed). Copy button.
7. Smoke per checklist.

## Tests

Manual smoke per checklist. No new unit tests.

## Smoke (browser)

```
1. Log in as Owner. /user/settings → side tab shows "Integrations".
2. Click it. Two cards: Google Ads (Not connected), Meta Ads (Not connected).
3. Click "Connect Google Ads" → Google consent → grant → land back, toast "Connected".
   Card now shows account email + accessible accounts list.
4. Expand an account → see list of Lead Forms.
5. Toggle "Subscribe" on the first form → POST creates a subscription row → toggle is on.
6. Webhook URL is shown with copy button. Copy → paste into Google Ads UI for that form
   (manual, outside our app).
7. Submit a test lead via Google Ads' "Send test data" button. Within ~5s, a new lead
   appears at /user/leads with the amber "Google Ads" badge.
8. Repeat 3–7 for Meta with a Facebook Page that has a lead-gen form. Subscribe toggles
   on the first form trigger backend Page-subscribe; toggling off the last form triggers
   Page-unsubscribe.
9. Disconnect Google → confirm modal → cards revert to "Not connected" state.
10. Reconnect: status returns; old subscriptions persist (since they FK to the integration
    record, which got re-created with the same id? — NO; on disconnect the integration
    row's tokens go null but the row remains, so subscriptions persist. Confirm in DB
    that subscriptions survive disconnect + reconnect.)
11. As Employee → Settings → Integrations is hidden. Direct URL → Access Denied.
```

## Risks

- **OAuth redirect with JWT:** the authorize endpoint is admin-auth but the redirect from Google to our callback also is — the user is logged into the CRM throughout. Verify the JWT cookie/header survives the redirect; if not, encode the JWT into the OAuth `state` (we already sign state with our key — easy to embed actor info).
- **Toggle UX for subscription:** subscribing creates a backend row. Network failure mid-toggle could leave UI/state out of sync. Optimistic update + revert on error; toast on failure.
- **Form list pagination:** Google Ads can return hundreds of forms. For v1, no pagination — list everything. If a customer complains, paginate later.
- **DLQ count link to placeholder:** Step 8 builds the full DLQ page. For Step 7 to be self-contained, link to a stub route that returns "DLQ UI coming in Step 8" or skip the link until Step 8 lands. Decision: render the count card without the link; Step 8 wires it.
- **Webhook URL secret rotation:** disconnecting Google rotates `webhook_secret` on next reconnect. Old URL in customer's Google Ads UI becomes invalid silently. Surface a warning on reconnect: "Re-paste the new webhook URL into Google Ads for each subscribed form."

## Rollback

Delete the new files. Revert settings route registration. Backend state (integrations + subscriptions) untouched.
