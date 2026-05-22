# Step 4 — Backend: Meta OAuth flow + auto-subscription

**Goal:** Implement Meta (Facebook + Instagram) OAuth flow and automatic webhook subscription. Unlike Google, Meta's webhook model is push-subscription: after OAuth the backend programmatically subscribes to the user's pages' lead_ads field via the Graph API, so leads start flowing without the user needing to paste any URLs.
**Track:** Ad Integrations
**Status:** Pending
**Depends on:** Step 1 (`integrations` table + crypto), Step 3 (subscription model — reused here), `META_APP_ID` + `META_APP_SECRET` + verify token env vars.

---

## Scope

In-scope:

- `core/integrations/meta/oauth.py`:
  - `start_authorize(org_id, actor) -> str` — Facebook OAuth consent URL with scopes `pages_show_list, pages_read_engagement, pages_manage_metadata, leads_retrieval, business_management`.
  - `handle_callback(code, state) -> Integration` — exchanges code → short-lived user token → long-lived user token → fetches the list of Pages and their per-Page tokens; persists. The user token is short-lived (60 days) but Page tokens derived from the long-lived user token are effectively non-expiring.
- `core/integrations/meta/api_client.py`:
  - `MetaGraphClient(integration)` — wraps `https://graph.facebook.com/v19.0/...` calls.
  - Refresh logic: if the user token expires, Meta requires re-OAuth (no refresh tokens). Detect expired-token errors, mark integration `expired`, surface in Settings UI.
- `core/integrations/meta/subscriptions.py`:
  - `list_pages(integration) -> list[MetaPage]` — `GET /me/accounts`.
  - `list_lead_forms_for_page(integration, page_id) -> list[MetaLeadForm]` — `GET /{page_id}/leadgen_forms`.
  - `subscribe_page(integration, page_id) -> None` — POST to `/{page_id}/subscribed_apps?subscribed_fields=leadgen` with the Page token. After this call, our webhook starts receiving deliveries for that Page's lead ads.
  - `unsubscribe_page(integration, page_id)` — symmetric DELETE.
  - On selecting a form via the Settings UI (Step 7), the backend ensures the parent Page is subscribed.
- `core/integrations/meta/router.py` — `/authorize`, `/callback`, `/pages`, `/pages/{page_id}/forms`, `/pages/{page_id}/subscribe`, `/pages/{page_id}/unsubscribe`.
- Env vars: `META_APP_ID`, `META_APP_SECRET`, `META_OAUTH_REDIRECT_URI`, `META_WEBHOOK_VERIFY_TOKEN` (random secret used during webhook URL verification dance in Step 5).
- Tests: token exchange (mocked), Page listing, subscribe/unsubscribe, expired-token detection.

Out of scope:

- Webhook receiver — Step 5.
- Field mapping — Step 8.
- Frontend — Step 7.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/integrations/meta/__init__.py` | created |
| `api/src/app/core/integrations/meta/oauth.py` | created |
| `api/src/app/core/integrations/meta/api_client.py` | created |
| `api/src/app/core/integrations/meta/subscriptions.py` | created |
| `api/src/app/core/integrations/meta/router.py` | created |
| `api/src/app/core/integrations/router.py` | modified — include the Meta subrouter |
| `api/src/app/shared/config.py` | modified — add `META_*` settings |
| `.env.example` | modified — add Meta vars |
| `api/tests/test_meta_oauth.py` | created |

**9 files.** Inside rule-8 budget.

## Plan

1. `oauth.py`:
   - Authorize URL: `https://www.facebook.com/v19.0/dialog/oauth?...`.
   - Callback exchanges code → short-lived token via `/v19.0/oauth/access_token`.
   - Exchanges short-lived → long-lived token via `/v19.0/oauth/access_token?grant_type=fb_exchange_token`.
   - Fetches the user's basic profile (`/me?fields=id,name,email`) for `account_label`.
   - Persists via `integrations.service.upsert(...)`.
2. `api_client.py`:
   - `_get_access_token()`: returns the decrypted user token. No refresh attempted (Meta doesn't issue refresh tokens; expiry forces re-OAuth).
   - On 401 from Graph API: set integration status to `expired`, raise `MetaTokenExpiredError`. Settings UI shows "Re-connect required."
3. `subscriptions.py`:
   - `list_pages`: `GET /me/accounts?fields=id,name,access_token`. Store Page tokens in memory only for the duration of the request (do not persist them long-term in v1; re-fetch each time we need to act on a Page). Future optimisation: persist Page tokens in a sibling table keyed by `(integration_id, page_id)`.
   - `list_lead_forms_for_page`: `GET /{page_id}/leadgen_forms?fields=id,name,status,leadgen_form_id`.
   - `subscribe_page`: `POST /{page_id}/subscribed_apps` with `subscribed_fields=leadgen` and the Page's access token.
   - `unsubscribe_page`: `DELETE /{page_id}/subscribed_apps`.
4. Wire endpoints in `meta/router.py`. Permission gate.
5. Test with `respx` mocking the Graph API endpoints.

## Tests

`api/tests/test_meta_oauth.py`:

- **Authorize URL shape:** correct domain, scope, redirect, state.
- **Callback flow (mocked):** mock short-token exchange, long-token exchange, userinfo. Verify integration row created with status `connected`.
- **List pages:** mock `/me/accounts` → returns 2 pages → parsed correctly.
- **List forms per page:** mock `/{page_id}/leadgen_forms` → returns 3 forms → parsed.
- **Subscribe page:** mock POST → success → no exception.
- **Unsubscribe page:** mock DELETE → success.
- **Expired token detection:** mock Graph API to return 401 OAuthException → `MetaTokenExpiredError` raised + integration status updates to `expired`.
- **Permission gate:** Employee → 403.

## Smoke

```powershell
# Set Meta env vars from a developer.facebook.com app
# META_APP_ID=...
# META_APP_SECRET=...
# META_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/integrations/meta/callback
# META_WEBHOOK_VERIFY_TOKEN=any-random-string-shared-with-meta-app-webhook-config

docker-compose restart api

# As Owner, navigate to /api/v1/integrations/meta/authorize in browser
# → Facebook consent → grant → redirected back

curl http://localhost:8000/api/v1/integrations -H "Authorization: Bearer $token"
# Expect: a meta_ads integration in connected status

curl http://localhost:8000/api/v1/integrations/meta/pages -H "Authorization: Bearer $token"
# Expect: list of pages the user manages

# Pick a page, list its forms
$pageId = "<id>"
curl "http://localhost:8000/api/v1/integrations/meta/pages/$pageId/forms" -H "Authorization: Bearer $token"

# Subscribe
curl -X POST "http://localhost:8000/api/v1/integrations/meta/pages/$pageId/subscribe" -H "Authorization: Bearer $token"
# Expect 200; future leads on this page's forms will hit our webhook (Step 5)
```

## Risks

- **App Review:** the `leads_retrieval` permission requires Meta App Review for production access. Test users in the app dashboard can grant this in dev mode without review. **Start App Review concurrently with this step's code; allow 1–2 weeks.**
- **Long-lived user tokens still expire:** after 60 days, the user must re-authorize. The Settings UI should surface a "your Meta connection expires on YYYY-MM-DD" notice (Step 8).
- **Page tokens vs. user tokens:** subscriptions need Page tokens (not user tokens). We fetch them per-request from `/me/accounts`. If a user revokes our app's access on Facebook, all Page tokens invalidate immediately; our next API call gets 401 and we mark `expired`.
- **App Webhook configuration:** in the Meta app dashboard's Webhooks tab, the `leadgen` field subscription is configured with our callback URL `https://api.furnicrm.app/api/v1/integrations/meta/webhook` and the verify token from env. This is one-time setup per environment (dev / staging / prod), done manually in the Meta UI. Document.
- **Instagram Lead Ads** share the same `leadgen` webhook field as Facebook; covered automatically. No separate integration needed.

## Rollback

Delete the new files. Revert router include + config + .env.example. The Meta API has no concept of "uninstall my OAuth app from the org" without the user revoking from Facebook; existing tokens become inert (we just stop calling them).
