# Reputation-warmup thresholds — locked

**Session:** 2026-09-21. Every value below carries either **(a)** a source URL fetched this session, **(b)** a citation to shipped in-repo code that has run against live Mailgun, or **(c)** an explicit `PROVISIONAL — no source` label so a future re-check can spot the gap.

Full context + gap analysis in [`DISCOVERY-NOTES.md`](DISCOVERY-NOTES.md). This file is the numeric shortlist Steps 2–7 read from.

---

## 1. Complaint (spam) rate — the primary reputation signal

| Value | Number | Source |
|---|---|---|
| Warmup soft-cap (fire warning to Owner) | **0.10%** | Gmail: "Keep spam rates reported in Postmaster Tools below 0.1%" — `support.google.com/mail/answer/81126` |
| Warmup hard-cap (auto-shed to platform-from) | **0.30%** | Gmail: "reaching 0.3% or higher" makes senders "ineligible for mitigation" — `support.google.com/mail/answer/81126` + Yahoo: same 0.3% — `senders.yahooinc.com/best-practices/` |
| Recovery window (auto-unshed) | **7 consecutive days below 0.3%** | Gmail: "spam rates remain below 0.3% for 7 consecutive days" — `support.google.com/a/answer/14229414` |
| Rolling window for calculation | **30 days** | PROVISIONAL — no explicit ISP source; align with Postmaster Tools' 30-day chart default |

**Semantic note:** these are ISP-reported spam rates measured against messages **delivered to inbox**, not accepted-at-Mailgun. Track 4 Step 4's evaluator must consume Mailgun's `complained` webhook events (not internal metrics) so the numerator matches the ISPs' own denominator.

---

## 2. Bounce rate — no ISP-published number

| Value | Number | Source |
|---|---|---|
| Warmup soft-cap | **2.0%** | PROVISIONAL — no ISP publishes a bounce cap. Prativani SES-shaped default; revisit if we see it fire in practice. |
| Warmup hard-cap | **5.0%** | PROVISIONAL — SES's own hard cap is 5%. Revisit if Mailgun surfaces a different number. |
| Rolling window | **30 days** | PROVISIONAL — matches complaint window. |

**Semantic note:** "bounce" = Mailgun's `permanent_fail` event. `temporary_fail` is a soft bounce and must NOT count toward this rate (transient blip vs address-doesn't-exist).

---

## 3. Bulk-sender threshold — auth + one-click required

| Value | Number | Source |
|---|---|---|
| Volume threshold | **5,000 msgs / 24h to Gmail** | Gmail FAQ: "any email sender that sends close to 5,000 messages or more to personal Gmail accounts within a 24-hour period" — `support.google.com/a/answer/14229414` |
| Scope | Primary domain + all sub-domains | Gmail FAQ (same URL): "All messages from the same primary domain count toward this threshold" |
| Bulk-sender status | **Permanent once assigned** | Gmail FAQ (same URL): "bulk sender status doesn't have an expiration date" |

**Auth requirements** for bulk senders (three-ISP consensus):

| Requirement | Gmail | Yahoo | Microsoft |
|---|---|---|---|
| SPF | ✅ required | ✅ required | ✅ required (May 2025) |
| DKIM | ✅ required | ✅ required | ✅ required (May 2025) |
| DMARC (`p=none` min.) | ✅ required | ✅ required | ✅ required (May 2025) |
| From-header alignment with SPF/DKIM | ✅ required | ✅ required (relaxed OK) | ⚠ not published |
| One-click unsub (RFC 8058) | ✅ required | ✅ required | ⚠ not published |

Sources: Gmail — `support.google.com/mail/answer/81126`; Yahoo — `senders.yahooinc.com/best-practices/`; Microsoft — `substrate.office.com/ip-domain-management-snds/postmaster`.

---

## 4. Mailgun webhook contract — locked from live-code + fetched docs

### 4.1 Event types (8) — from `documentation.mailgun.com/.../webhooks/webhooks/`

| Event | Semantic |
|---|---|
| `accepted` | Mailgun accepted the send request; message queued |
| `delivered` | Recipient's server accepted the message |
| `temporary_fail` | Soft bounce; Mailgun will retry |
| `permanent_fail` | Hard bounce; delivery abandoned |
| `opened` | Recipient viewed the message (needs CNAME tracking DNS) |
| `clicked` | Recipient clicked a link (needs CNAME tracking DNS) |
| `unsubscribed` | Recipient hit an unsubscribe link |
| `complained` | Recipient marked as spam |

**Track 4 uses:** `delivered` (numerator for open/click rates), `permanent_fail` (bounce counter), `complained` (complaint counter), `unsubscribed` (informational). `opened` / `clicked` require enabling the CNAME tracking DNS — decide per-track.

### 4.2 Retry policy — from `.../webhook-retries/`

- **Window:** 8 hours.
- **Backoff:** 5min → 10min → 15min → 1h → 2h → 4h.
- **Success:** HTTP 200 (no retry).
- **Explicit reject:** HTTP 406 (no retry).
- **Any other status:** retried per schedule above.
- **Terminal failure:** 8h elapsed → Mailgun stops.

**Track 4 implication:** the events webhook receiver MUST return HTTP 200 on successful ingest, HTTP 406 on structural rejection (bad signature, unknown org), and let ANY other error path bubble up as a 5xx so Mailgun retries.

### 4.3 Signature verification — pinned from shipped code

Source: [`API/src/app/core/email/mailgun/service.py:verify_signature`](../../API/src/app/core/email/mailgun/service.py). Mailgun's docs 404'd; this shipped code has run against live Mailgun since the mailgun-inbound track's Step 7 smoke.

- **Formula:** `HMAC-SHA256(key = MAILGUN_SIGNING_KEY, input = (timestamp + token))`, hex digest, constant-time compare via `hmac.compare_digest`.
- **Timestamp skew:** ±300 seconds (5 minutes).
- **Key source:** `MAILGUN_SIGNING_KEY` env var; optional `MAILGUN_SIGNING_KEY_PREVIOUS` for zero-loss rotation.

**Track 4 reuses this exact function** for the events webhook — one signing key across inbound + events (Mailgun uses one key per account).

---

## 5. Mailgun rate limits — headers, not numbers

| Signal | Value | Source |
|---|---|---|
| Rate-limit header (limit) | `X-RateLimit-Limit` | `documentation.mailgun.com/.../api-overview` |
| Rate-limit header (remaining) | `X-RateLimit-Remaining` | same |
| Rate-limit header (reset) | `X-RateLimit-Reset` (UTC ms) | same |
| Rate-exceeded response | HTTP 429 + `Retry-After` | same |
| **Numeric cap** | **NOT PUBLISHED** by Mailgun | same — "Time windows may vary by API depending on resource usage" |

**Track 4 send-gate must consume the response headers.** Cannot precommit a per-hour cap. The shipped `MailgunApiClient` already handles 429 via `_parse_retry_after` — reuse for the outbound send calls Step 5 wires.

---

## 6. Reputation scope — provisional (per-domain assumption)

**Assumption locked:** Mailgun reputation is treated as **per-domain** for Track 4's evaluator. If the confirmatory smoke (Step 3 or Step 4) reveals it's actually account-wide, our per-domain thresholds still fire correctly — they'll just fire simultaneously for every domain on the account rather than isolating the drift.

Evidence supporting per-domain (from Mailgun surfaces that DID load):
- Sending Domains are DNS-configured per-domain (Track 2 shipped).
- Suppression list is scoped per-domain (`.../tracking-messages` docs).
- Webhook configuration is available per-domain or account-wide.
- Mailgun's help article on reputation itself is **unreachable** (403); the direct-source answer stays open.

**Confirm during Step 3 smoke** — see [`DISCOVERY-NOTES.md`](DISCOVERY-NOTES.md) §Reputation scope — evidence path.

---

## 7. Warmup ladder — SES-Prativani provisional

**Every number in this section is PROVISIONAL — no ISP-published source.** Prativani's SES-shaped defaults are the starting point; revisit after 30 days of production data.

| Day | Max sends/day | Notes |
|---|---|---|
| 1 | 50 | First-day cap. All to opted-in high-engagement seed list. |
| 2 | 100 | Doubling ladder. |
| 3 | 500 | |
| 4 | 1,000 | |
| 5 | 5,000 | Crosses Gmail bulk-sender threshold — auth verification must be green by day 5. |
| 6 | 10,000 | |
| 7+ | 25,000 → +25% daily | Until steady-state cap or complaint/bounce breach. |
| Steady state cap | Provider-driven | Mailgun's rate-limit headers gate. |

**Provisional rationale:** these mirror SES's published warmup schedule. Mailgun doesn't publish a warmup guide (their reputation article is behind the 403 wall). Track 4 Step 4 (evaluators) reads these caps from a config file so the manager can tune without a code change.

---

## Summary — what's locked vs what's provisional

| Category | Status |
|---|---|
| Complaint-rate thresholds (0.10% / 0.30%) | **LOCKED** — Gmail + Yahoo triangulate |
| 7-day recovery window | **LOCKED** — Gmail FAQ |
| Bulk-sender = 5,000 msgs/day | **LOCKED** — Gmail FAQ |
| Auth requirements (SPF+DKIM+DMARC+one-click) | **LOCKED** — 3-ISP consensus |
| Mailgun event types (8) | **LOCKED** — docs fetched |
| Mailgun webhook retry policy | **LOCKED** — docs fetched |
| Mailgun signature formula | **LOCKED** — shipped code |
| Mailgun rate-limit headers | **LOCKED** — docs fetched (headers only) |
| Bounce-rate thresholds (2% / 5%) | **PROVISIONAL** — SES-shaped, revisit |
| Rolling-window duration (30d) | **PROVISIONAL** — align with Postmaster Tools |
| Reputation scope (per-domain) | **PROVISIONAL** — Mailgun docs blocked, confirm via smoke |
| Warmup ladder day-by-day caps | **PROVISIONAL** — SES-shaped, revisit after 30d live data |
| Mailgun `v:` custom-var limits | **DEFERRED** — pin empirically during Step 6 stamping smoke |
| Cross-ESP benchmarks (SendGrid / Mailchimp / Klaviyo) | **DEFERRED** — rule zero forbids memory; follow-up fetch pass needed |
