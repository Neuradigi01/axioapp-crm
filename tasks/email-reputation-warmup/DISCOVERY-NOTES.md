# Discovery notes — email-reputation-warmup Step 1

**Session:** 2026-09-21. Timebox: 4h (extended for this critical step).

Every numeric claim in the sibling [`THRESHOLDS-LOCKED.md`](THRESHOLDS-LOCKED.md) traces back to one of the URLs in the **Fetched** table below, OR to shipped in-repo code that ran against a live Mailgun sandbox during earlier tracks. **Nothing here is recalled from memory** (per [`DISCOVERY_RULES.md`](../../DISCOVERY_RULES.md) rule zero). Where a URL didn't resolve, the gap is declared explicitly.

## Fetched — URLs that returned meaningful content this session

| # | Purpose | URL | Verdict |
|---|---|---|---|
| 1 | Mailgun webhook event types (8 types) | https://documentation.mailgun.com/docs/mailgun/user-manual/webhooks/webhooks/ | ✅ full event list |
| 2 | Mailgun webhook retry policy | https://documentation.mailgun.com/docs/mailgun/user-manual/webhooks/webhook-retries/ | ✅ full schedule |
| 3 | Mailgun API rate-limit headers | https://documentation.mailgun.com/docs/mailgun/api-reference/api-overview | ⚠ headers only, NO published numbers |
| 4 | Google Gmail sender guidelines (Feb 2024) | https://support.google.com/mail/answer/81126 | ✅ 0.1% / 0.3% thresholds |
| 5 | Google email-sender FAQ | https://support.google.com/a/answer/14229414 | ✅ bulk-sender definition + 7-day recovery |
| 6 | Yahoo sender best practices | https://senders.yahooinc.com/best-practices/ | ✅ 0.3% + SPF/DKIM/DMARC + one-click |
| 7 | Microsoft Outlook.com postmaster | https://substrate.office.com/ip-domain-management-snds/postmaster (via 308 redirect from `sendersupport.olc.protection.outlook.com/pm/`) | ⚠ auth requirements only, no complaint thresholds |
| 8 | Mailgun tracking overview | https://documentation.mailgun.com/docs/mailgun/user-manual/user-manual/tracking-messages | ⚠ high-level only — event schemas + `v:` params NOT surfaced |

## Gaps — URLs the step spec listed but that didn't return meaningful content

1. **Mailgun sender-reputation article** (`help.mailgun.com/hc/en-us/articles/360012573294-Managing-Your-Sender-Reputation`) → **HTTP 403** (Zendesk CDN block). Same block that hit Track 3 Step 1. The load-bearing question — "is reputation account-scope or per-domain?" — **remains unanswered from Mailgun's own docs this session**. See "Reputation scope — evidence path" below for what we can pin from adjacent Mailgun surfaces.

2. **Mailgun rate-limit numbers.** Their API-overview page (fetched, #3 above) is explicit that specific rate-limit numbers **are not published**: "Time windows may vary by API depending on resource usage… Retry as defined in response headers." The API surfaces `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` and returns HTTP 429 when exceeded — but the numeric cap is a runtime property, not a documented constant. The warmup engine must read these headers rather than precommit a cap.

3. **Mailgun `v:` custom variables** (max count, max value length, allowed charset). 7 URL variations on `documentation.mailgun.com/.../attaching-data-to-messages/` / `custom-message-variables/` / `message-parameters/` all returned 404. The shipped MailgunApiClient (Track 2) only uses `o:tag` and `o:tracking`, so we have working-code precedent for those two but not for `v:`. Track 4 Step 6 (v-stamping) plans to attach `v:message_id` / `v:tenant_id` / `v:endpoint_type` — the smoke that step ships will pin the real behaviour empirically.

4. **Mailgun webhook signature verification page** — every URL 404'd (`/webhook-signature/`, `/verifying-webhooks/`, `/webhook-security/`, etc.). **Signature formula pinned from shipped code** instead: [`API/src/app/core/email/mailgun/service.py:verify_signature`](../../API/src/app/core/email/mailgun/service.py) — HMAC-SHA256 over `timestamp + token` with `MAILGUN_SIGNING_KEY`, 5-minute skew window, `hmac.compare_digest` constant-time compare, optional rotation via `MAILGUN_SIGNING_KEY_PREVIOUS`. That code has been running against live Mailgun since the mailgun-inbound track shipped — reused by the events webhook per assumption.

5. **Microsoft SNDS reputation bands** (Red / Yellow / Green). The `substrate.office.com/…/postmaster` page confirms Microsoft **doesn't publish the numeric thresholds** — it lists auth requirements + a "junk / reject" enforcement policy but no complaint-rate cap. Aligns with the industry pattern (only Google publishes a hard number).

6. **Yahoo Postmaster reputation page** (`senders.yahooinc.com/postmaster/`) → 404 directly. Yahoo best-practices page (fetched, #6 above) covers the sender requirements verbatim, which is what the threshold work actually needs.

## Mailgun webhook event types — verbatim

Source: URL #1 above (Mailgun webhooks docs).

| Event | Fires when |
|---|---|
| `accepted` | "Mailgun accepted the request to send/forward the email and the message has been placed in queue" |
| `delivered` | Message successfully accepted by recipient's email server |
| `temporary_fail` | "Delivery delayed due to temporary issues; retries will occur" |
| `permanent_fail` | "Delivery failed permanently; no further attempts will be made" |
| `opened` | Recipient opened email with image viewing enabled (needs CNAME tracking DNS) |
| `clicked` | Recipient clicked a link in the email (needs CNAME tracking DNS) |
| `unsubscribed` | "Recipient clicked the unsubscribe link" |
| `complained` | "Recipient filed a spam complaint" |

Additional facts (verbatim from URL #1):

- **Delivery method:** "Mailgun will send an HTTP or HTTPS POST request with a JSON payload to the endpoint you specify when an event occurs."
- **Configuration levels:** "Webhooks can be set at account or domain level, with selective event filtering available."
- **Tracking prerequisites:** "Open and click tracking require CNAME records pointing to mailgun.org; unsubscribe tracking must be enabled in the control panel."

## Mailgun webhook retry policy — verbatim

Source: URL #2 above.

- **Window:** 8 hours from the first failed POST.
- **Backoff schedule:** 5 min → 10 min → 15 min → 1 h → 2 h → 4 h (exponential).
- **Success:** HTTP 200 → no retry.
- **Explicit reject:** HTTP 406 → no retry.
- **All other status codes:** retry per schedule above.
- **Terminal failure:** after the 8-hour window elapses.
- **Delivery notifications:** excluded from automatic retries entirely (per the docs — different code path).

## Mailgun API rate-limit signal — verbatim

Source: URL #3 above.

- **Base URLs:** `https://api.mailgun.net/` (US), `https://api.eu.mailgun.net/` (EU).
- **Rate-limit headers on every response:**
  - `X-RateLimit-Limit` — "Total calls that can be made in each time window"
  - `X-RateLimit-Remaining` — "Calls remaining in the given time window"
  - `X-RateLimit-Reset` — "Unix milliseconds (UTC) until the limit resets"
- **On exceed:** HTTP 429, "Retry as defined in response headers".
- **No published numeric cap:** "Time windows may vary by API depending on resource usage."

**Implication for Track 4:** the send-gate chain (Step 5) must consult the response headers rather than precommit a cap. This is aligned with the shipped `MailgunApiClient` retry policy (Track 2 Step 2) which already handles 429 via `Retry-After`.

## Reputation scope — evidence path (not a direct fetch)

The load-bearing question is whether Mailgun reputation is **account-wide** or **per-domain**. The direct-source article was blocked (gap #1). We can infer from adjacent surfaces:

- Mailgun exposes **per-domain** DNS records (SPF, DKIM per domain in the Sending Domains flow — shipped Track 2).
- Mailgun **webhook configuration** allows account-level OR domain-level subscription (per URL #1).
- Mailgun's Suppressions (unsubs, bounces, complaints) are stored **per-domain** — confirmed by URL #8 ("automatically added to the suppression list for that domain").
- Mailgun's Routes API is **account-scoped** (one route matches across all domains on the account) — see [`API/src/app/scripts/mailgun_route_setup.py`](../../API/src/app/scripts/mailgun_route_setup.py).

**Provisional finding:** reputation-influencing signals (suppressions, DKIM alignment) are stored **per-domain**, but the account itself likely carries an aggregate signal that shows up in Mailgun's own dashboard. **Confirm empirically during Step 3 smoke by pointing two sub-domains at the same account and watching Mailgun's reputation panel.** Until that smoke lands, Track 4 designs against the **per-domain assumption** (safer — if reputation is actually account-wide, per-domain thresholds still catch the drift; if per-domain is right, our thresholds fire at the right resolution).

## ISP thresholds — pinned

### Gmail (URLs #4 + #5)

- **Bulk sender definition** (verbatim): "any email sender that sends close to 5,000 messages or more to personal Gmail accounts within a 24-hour period." All sub-domains roll up to the primary domain for this count. **Bulk-sender status is permanent** once set.
- **Spam rate thresholds:**
  - **Recommended:** "below 0.1%"
  - **Hard limit:** "reaching 0.3% or higher" — "user-reported spam rates greater than 0.3% will be ineligible for mitigation" (as of June 2024).
  - **Recovery band:** "spam rates remain below 0.3% for 7 consecutive days" restores mitigation eligibility.
- **Auth requirements** for bulk senders: SPF + DKIM + DMARC; From-header domain aligned with SPF or DKIM.
- **One-click unsubscribe:** required for marketing / subscribed mail. RFC 8058 POST method preferred; mailto acceptable.
- **Enforcement timeline:** Feb 2024 (initial), Nov 2025 ("ramping up its enforcement on non-compliant traffic").

### Yahoo (URL #6)

- **Spam rate threshold:** "Keep your spam rate below 0.3%" — same hard cap as Gmail. Calculated on delivered-to-inbox mail.
- **Auth requirements** for bulk senders: both SPF + DKIM required; DMARC with at least `p=none`; relaxed alignment permitted.
- **One-click unsubscribe:** required for marketing / subscribed mail.
- **Feb 2024 alignment:** Yahoo enforced its own version of the same 0.3% + auth + one-click rules on the same timeline.

### Microsoft (URL #7)

- **Auth requirements** for high-volume senders (>5,000 msgs/day) as of **May 5, 2025**: SPF + DKIM + DMARC.
- **Enforcement:** initially route to junk; eventually reject non-authenticated messages until DNS records configured.
- **Numeric complaint / bounce thresholds:** not published by Microsoft. SNDS surfaces data internally in per-IP bands (Red / Yellow / Green) but does NOT expose the numeric boundaries.

## Interim competitor recall (marked unsourced — per DISCOVERY_RULES rule zero)

The step spec asked for interim SendGrid / Mailchimp / Klaviyo recall. **This section is deliberately empty.** Rule zero forbids answering from memory, and I could not fetch those competitor docs this session (their pages sit behind marketing walls that would return generic listing content, not the technical warmup-ladder numbers we need). If Track 4 depends on cross-ESP benchmarking, a follow-up Step should attempt those fetches OR the manager should call the numbers by policy rather than by comparison.

## Open items for later steps

1. **Reputation-scope confirmation** — smoke during Step 3 (see "Reputation scope — evidence path" above).
2. **Mailgun `v:` custom-variable limits** — pin empirically via Step 6's stamping smoke.
3. **Bounce-rate threshold** — no ISP publishes a numeric bounce-rate cap comparable to the 0.3% complaint cap. Track 4's warmup engine likely needs an internal cap derived from Prativani's SES-shaped defaults; flag for the Step 4 evaluator design.
4. **Mailgun webhook signature verification page** — if a working URL surfaces, verify our shipped `verify_signature` code matches (it already runs against live Mailgun; low priority).
5. **SendGrid / Mailchimp / Klaviyo warmup ladders** — need real doc URLs to benchmark; flag for a follow-up discovery pass if warmup-cadence differs from SES-Prativani defaults.
