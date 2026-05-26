# Google Ads API Integration — Design Document

**Applicant:** Neuradigi Technologies
**Tool Name:** CRM
**MCC ID:** 938-729-9841
**Contact:** neuradigi01@gmail.com
**Date:** 26 May 2026
**API Access Tier Requested:** Basic Access

---

## 1. Tool Overview

Neuradigi Technologies is building a multi-tenant SaaS Customer Relationship Management (CRM) platform for small and mid-sized businesses in India. The CRM is sold on a monthly subscription basis.

Each customer (a business running Google Ads to acquire new customers) connects their own Google Ads account to our CRM via Google's standard OAuth 2.0 authorization flow. Once connected, leads submitted through their Google Ads **Lead Form Extensions** are automatically delivered into the CRM in real time, allowing the customer's sales team to follow up immediately.

**The integration is effectively read-only on the customer's Google Ads account.** The only state-changing operation is the one-time webhook subscription registration, which Google itself authorises and exposes for the purpose of receiving lead form submissions.

We do not run, create, modify, pause, schedule, budget, bid, or report on ad campaigns programmatically. We do not push any data back to Google Ads.

---

## 2. System Architecture

The CRM uses a standard three-tier web architecture with an async worker pool:

**Data flow:**

1. The customer's browser loads the CRM frontend (Angular Single Page Application). From the Settings page, the customer initiates the OAuth flow to connect their Google Ads account.
2. The CRM Backend (FastAPI, Python 3.13) handles the OAuth callback, performs the code-for-token exchange with Google's token endpoint, and persists encrypted tokens.
3. PostgreSQL 17 stores all tenant data with Postgres Row-Level Security (RLS) for multi-tenant isolation. Refresh tokens are encrypted at rest with Fernet (AES-128-GCM).
4. Google delivers Lead Form Extension submissions to a webhook endpoint on the CRM Backend.
5. A Celery worker pool (with Redis broker) consumes webhook events asynchronously, retrieves the full lead via the Google Ads API, applies the customer's field mapping, and writes the resulting contact and lead rows back into PostgreSQL.
6. The customer's CRM frontend reads from PostgreSQL via the FastAPI Backend, displaying the new leads in real time.

### Components

| Component | Technology | Purpose |
|---|---|---|
| Frontend | Angular 20 | Customer-facing CRM UI; settings page initiates OAuth |
| Backend | Python 3.13 + FastAPI | OAuth handling, webhook receiver, lead ingestion |
| Database | PostgreSQL 17 with Row-Level Security | Multi-tenant storage; tokens encrypted at rest |
| Async Workers | Celery + Redis | Webhook payload processing, retry on failure |
| Encryption | Fernet (AES-128-GCM) | Refresh token encryption; master key in env secret |

---

## 3. OAuth 2.0 Authorization Flow

We use the standard OAuth 2.0 Authorization Code flow as documented by Google.

### Step-by-step

1. **User initiates connection.** Inside the CRM Settings page, the customer (a business owner) clicks "Connect Google Ads."
2. **Redirect to Google's consent screen.** The CRM redirects the browser to Google's standard OAuth authorization endpoint at `https://accounts.google.com/o/oauth2/v2/auth` with the following parameters:
    - `client_id` — our registered OAuth Client ID
    - `redirect_uri` — `https://api.<our-domain>/api/v1/integrations/google/callback`
    - `response_type` — `code`
    - `scope` — `adwords openid userinfo.email`
    - `access_type` — `offline` (to obtain a refresh token)
    - `prompt` — `consent` (to force consent screen on every authorization)
    - `state` — an HMAC-signed nonce binding the org_id, user_id, and a 10-minute TTL
3. **User consents on Google's hosted screen.** Google displays the requested scopes; the customer reviews and clicks "Allow."
4. **Google redirects back with an authorization code.** Browser is redirected to our callback URL with `?code=...&state=...`.
5. **State validation.** The CRM verifies the HMAC signature on `state` and confirms it has not expired. Invalid or expired state → 403.
6. **Code-for-token exchange.** Backend POSTs to `https://oauth2.googleapis.com/token` with the authorization code, client ID, client secret, and redirect URI. Receives `access_token`, `refresh_token`, `id_token`, and `expires_in`.
7. **Token storage.** Refresh token is encrypted with Fernet and stored in the `integrations` table, scoped to the customer's organization (org_id).
8. **Customer info fetch.** Using the access token, backend calls `GoogleAdsService.list_accessible_customers` to enumerate which Ads accounts the user manages, and stores those in our `integration_accounts` table.

### Scopes Requested

| Scope | Purpose |
|---|---|
| `.../auth/adwords` | Google Ads API access — required for listing accounts, listing lead forms, retrieving lead submissions |
| `openid` | Standard OIDC identifier scope |
| `.../auth/userinfo.email` | Display the connected Google account's email in the CRM Settings UI |

---

## 4. Google Ads API Services Used

The CRM uses only the following Google Ads API services, all of which are read-only on the customer's data except where noted:

| Service | Method | Purpose | Mutates? |
|---|---|---|---|
| `CustomerService` | `list_accessible_customers` | Enumerate the Ads accounts the connected user has access to | No |
| `GoogleAdsService` | `search` / `search_stream` | Query customer metadata, campaigns, ad groups, ads for lead-attribution display in the CRM UI | No |
| `LeadFormSubmissionDataService` (or current equivalent) | List lead form submissions on webhook delivery | Retrieve the field values + campaign/ad metadata for each delivered lead | No |
| Webhook subscription | Lead Form Extension webhook registration | One-time subscription to receive lead form submissions for the chosen forms | Yes — but only the webhook subscription record itself; no campaign/ad data is changed |

We do **NOT** call:
- `CampaignService` mutate operations
- `AdGroupService` mutate operations
- `AdService` mutate operations
- Any budget or bidding service
- `ConversionUploadService` (no data push-back)
- Any reporting/analytics export beyond lead-attribution metadata

---

## 5. Lead Ingestion Flow

The end-to-end lead ingestion sequence is as follows:

1. The customer's ad runs on Google Ads with a Lead Form Extension attached.
2. An end-user fills the lead form on a Google surface (Search, YouTube, or Display).
3. Google delivers a webhook POST to the CRM's webhook endpoint at `https://api.<our-domain>/api/v1/integrations/google/webhook`. The payload contains the lead_id, form_id, customer_id, campaign_id, and ad_id.
4. The CRM verifies the webhook signature using the shared secret issued by Google during webhook registration. Invalid signatures are rejected with HTTP 401 and logged.
5. The webhook handler enqueues a Celery task and returns HTTP 200 immediately (within 250ms, to satisfy Google's webhook latency requirement).
6. The Celery worker then performs the following steps:
    - Looks up the integration row by customer_id.
    - Fetches a valid access token, refreshing via the stored refresh token if the access token has expired.
    - Calls the Google Ads API to retrieve the lead's field values and campaign/ad attribution metadata.
    - Applies the customer's field mapping (saved in CRM Settings) to convert the Google field names into CRM contact and lead fields.
    - Creates the contact and lead records in the CRM database scoped to the customer's org_id, with attribution metadata (campaign_id, ad_id, form_id) preserved for display.
7. The new lead immediately surfaces in the customer's CRM Leads view.

### Retry & Idempotency

- Failed lead-retrieval calls retry with exponential backoff (max 5 retries).
- Idempotency check: each lead's Google-side `lead_id` is unique per org. Duplicates are no-ops + audit-logged.
- Exhausted retries → routed to a Dead Letter Queue (DLQ) table for the org's admin to inspect.

---

## 6. Token & Data Security

| Concern | Mitigation |
|---|---|
| Token storage | Refresh tokens encrypted at rest with Fernet (AES-128-GCM). Master key in environment-only secret; never committed to source control. |
| Token transmission | All API traffic over TLS 1.2+. Tokens never sent to the frontend or logged. |
| Multi-tenancy isolation | Postgres Row-Level Security (RLS) enforces that each org_id can only see its own integration rows, tokens, and ingested leads. RLS is implemented on every table that holds tenant data. |
| Token revocation | When a customer clicks "Disconnect" in CRM Settings, the backend calls Google's `/revoke` endpoint, deletes the stored refresh token, and tombstones the integration row. |
| Master key rotation | Documented rotation procedure: new key generated → all existing encrypted tokens re-encrypted in a transactional batch → old key destroyed. |
| Audit logging | Every Google Ads API call made on behalf of a customer is logged with timestamp, endpoint, org_id, and outcome. Admins can view this log in the CRM. |
| Access control | Only org members with the `integrations.manage` permission can connect, disconnect, or modify the Google Ads integration. |

---

## 7. Required Minimum Functionality (RMF) Compliance

| RMF Item | How we comply |
|---|---|
| **UI access to all API-retrieved data** | All ingested leads (with full field values + campaign attribution) are viewable in the CRM Leads page. Field-level detail and source attribution are searchable and filterable. |
| **No automated/bulk operations not exposed to user** | All operations are triggered by user action: explicit OAuth consent, explicit subscription selection per form, explicit disconnect. No background mutations occur. |
| **No misrepresentation of data** | We display data as-received from Google with attribution to the originating campaign/ad. We do not transform or aggregate ad performance metrics. |
| **No deceptive practices** | Customers see the exact scopes requested on Google's consent screen, can review their connected integrations in CRM Settings, and can disconnect/revoke at any time. |
| **Required disclosures** | Our Privacy Policy (https://neuradigi.com/privacy) discloses what data we receive from Google, how it's stored, and how customers can request deletion. |

---

## 8. User Interface (Settings → Integrations page)

The customer's view in the CRM:

1. **Settings → Integrations** lists connected ad platforms.
2. Each integration shows: connection status, connected Google account email, last sync time, number of leads received in the last 30 days.
3. "Connect Google Ads" button initiates the OAuth flow described in Section 3.
4. After OAuth, the customer selects which Lead Forms to subscribe to from a dropdown populated by `list_accessible_customers` → `search` calls.
5. For each selected form, the customer maps Google's lead fields to CRM contact/lead fields (form mapping editor).
6. "Disconnect" button revokes tokens and removes the integration.

*(UI screenshots / mockups available on request; product is in active development and not yet publicly launched.)*

---

## 9. Customer Base & Volume

| Metric | Estimate |
|---|---|
| Current paying customers | 0 (pre-launch, dev/Testing mode with seed test users only) |
| Projected 6-month customers | ~20 SMBs in India |
| Projected 12-month customers | ~100 SMBs in India |
| Projected API operations per customer per day | < 100 (mostly webhook-driven lead retrievals) |
| Projected total daily ops in 12 months | ~10,000 (well within the Basic Access 15,000/day cap) |

---

## 10. Compliance & Policy Adherence

- We acknowledge and will continue to comply with the Google Ads API Terms of Service.
- We acknowledge and will continue to comply with the Required Minimum Functionality policy.
- We will keep our Privacy Policy and Terms of Service publicly accessible and current.
- We will retain audit logs of API operations for a minimum of 90 days.
- We will not share, resell, or expose Google Ads data to third parties outside the customer's own CRM tenancy.

---

## 11. Contact

For any questions about this design document or our integration:

- **Email:** neuradigi01@gmail.com
- **Company:** Neuradigi Technologies
- **Website:** https://neuradigi.com
- **MCC:** 938-729-9841

---

*End of design document.*
