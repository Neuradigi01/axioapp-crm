"""Meta (Facebook + Instagram) Ads OAuth + Graph API subpackage.

Symmetric to `core/integrations/google/` — same `oauth.py /
api_client.py / subscriptions.py / router.py` layout. Step 5 will add
`webhook.py` + `tasks.py` to receive Lead-Ad deliveries.

Meta differs from Google in three ways worth noting at module level:

  - **No refresh tokens.** Meta issues a short-lived user token (1 hr)
    that we immediately exchange for a long-lived user token (60 days).
    When the long-lived token expires, the Owner must re-OAuth — there
    is no programmatic refresh. `api_client` detects 401 and flips the
    integration row to `expired` so the Settings UI can prompt.

  - **Webhook subscription is push, not pull.** After OAuth, we POST to
    `/{page_id}/subscribed_apps` for each selected Page. Once subscribed,
    Meta delivers `leadgen` events to our webhook URL (configured ONCE
    per environment in the Meta app dashboard, NOT per integration —
    that's how Meta's webhook model works). Step 5 builds the receiver.

  - **Page tokens are derived per-request.** A user-token GET on
    `/me/accounts` returns each Page's access_token alongside its id +
    name. We don't persist Page tokens in v1; each `subscribe_page` /
    `unsubscribe_page` call re-fetches them. Simpler + safer (a Page
    token revoked on Facebook stops working immediately for us too).

Both Facebook and Instagram Lead Ads share the same `leadgen` webhook
field, so no separate Instagram integration is needed.
"""
