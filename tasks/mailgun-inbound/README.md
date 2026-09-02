# Mailgun Inbound — Reply-Capture for SMTP Senders

Add an inbound-receive channel via **Mailgun Routes** so replies to CRM email sent through the manual SMTP backend (`tbl_email_smtp_senders`) land back in the same conversation. Gmail and Microsoft OAuth mailboxes already do send + receive via their own sync; this track does **NOT** touch them.

**Status:** Pending — plan drafted 2026-09-02, revised 2026-09-02 after PLANNING_RULES Part C reviewer gate (Attacker + Architect + Absence). All C/H findings folded in below; disagreements recorded where they exist.

## Why this track exists

Manual SMTP senders can send but cannot receive replies — SMTP is a one-way protocol from our side, and this codebase never implemented IMAP (memory `project_email_body_extraction_fix.md`: *"SMTP is outbound-only (no IMAP path exists)."*). Every mail sent through `OrgSmtpBackend` is a one-way conversation: the customer replies, the reply goes to the sender's mailbox at the client's own email provider, and nothing lands in the CRM.

Gmail and Microsoft OAuth mailboxes do not have this problem — the sync daemon in [`core/email/gmail`](API/src/app/core/email/gmail/) and [`core/email/microsoft`](API/src/app/core/email/microsoft/) pulls the reply back into `tbl_messages` via `receive_email` in [`core/conversations/adapters/email.py:574`](API/src/app/core/conversations/adapters/email.py#L574). SMTP has no equivalent.

**Industry standard fix:** rewrite the `Reply-To` header on outbound SMTP mail to a per-sender opaque address at a receiving domain we control, and use an inbound provider (Mailgun / Postmark / SendGrid Inbound Parse / AWS SES Inbound) to receive replies via HTTP webhook. HubSpot Connected Inbox, Front, Close, and Missive all use this pattern. Mailgun is picked here because it has a mature Routes API, low pricing, and a sandbox tier suitable for dev without any DNS ceremony.

## What this track does

- **New column `inbound_token VARCHAR(32) UNIQUE` + `capture_replies_in_crm BOOLEAN NOT NULL DEFAULT true` on `tbl_email_smtp_senders`.** Token is 12-char URL-safe (base64url via `secrets.token_urlsafe(9)`, sliced to 12), generated on sender-create, backfilled for existing rows. `capture_replies_in_crm` is a per-sender opt-out (HubSpot parity — a small-business owner running SMTP against their own Gmail app-password may want replies to land back in Gmail, not the CRM); when `false`, we do NOT rewrite Reply-To on their outbound.
- **`Reply-To` header injection is 3 lines, not a new capability.** [`send_email()`](API/src/app/core/conversations/adapters/email.py#L229) and [`_build_outbound_mime()`](API/src/app/core/conversations/adapters/email.py#L863) already accept `reply_to: str | None`. Only change: inside `send_email()`, when `smtp_sender_id is not None` AND `smtp_sender.capture_replies_in_crm is True` AND `smtp_sender.inbound_token is not None`, compute `reply_to = f"in_{token}@{INBOUND_EMAIL_DOMAIN}"` and pass it through. Any caller-supplied `reply_to` is REPLACED (SMTP-capture is authoritative), and the original is preserved in `Message.payload.original_reply_to` for audit. OAuth backends (`OrgOauthBackend`) never receive this treatment.
- **New sub-module at `core/email/mailgun/`** — parallel to existing `core/email/gmail/` and `core/email/microsoft/`. Five files per the layered convention: `schemas.py`, `router.py`, `service.py`, `data_access.py`, plus `tasks.py` for the Celery worker. No `models.py` (no new tables owned by this sub-module — the two new tables live where they belong: SMTP-sender columns on `email_senders`, failed-deliveries on `email_senders/dlq`, message auth columns on `conversations`).
- **New public webhook `POST /api/v1/webhooks/mailgun/inbound`.** Mailgun HMAC-SHA256 signature verification, formula spelled out verbatim: `hmac.new(MAILGUN_SIGNING_KEY.encode("utf-8"), (timestamp + token).encode("utf-8"), hashlib.sha256).hexdigest()`, constant-time compared against the `signature` field. Reject if `abs(now - int(timestamp)) > 300` (5-min window). Redis replay cache `mgw:seen:<token>` (10-min TTL, `nx=True set` — first writer wins) rejects the same Mailgun-delivery `token` twice. Copies the auth-first-then-enqueue pattern from [`core/integrations/meta/webhook.py`](API/src/app/core/integrations/meta/webhook.py).
- **Rotation-friendly signing key: `MAILGUN_SIGNING_KEY` + optional `MAILGUN_SIGNING_KEY_PREVIOUS`.** Verify tries the current key first, falls back to previous when set. Rotation is: promote current → previous, install new current. Zero-inbound-loss cutover window.
- **Constant-time response — all work happens in Celery.** Webhook verifies signature, persists raw payload + attachments to `./storage/pending-inbound/{uuid}/` on disk (payload.json + attachment_N files), enqueues a task with the disk path, returns 200. This addresses THREE reviewer findings at once: (a) no token-existence oracle via response timing — the request path never touches the sender-lookup DB; (b) 25 MB payloads don't ride through Redis/RabbitMQ; (c) if the Celery broker is down after we return 200, a cron sweeper picks up pending-inbound directories older than 5 min and re-enqueues.
- **Rate-limit only on signature-verify failures**, not on signed traffic. Signed = trusted = Mailgun; rate-limiting the pool of Mailgun IPs punishes legit deliveries during reply-storms. Failed-signature IPs shed at 20 req/min via `shared.rate_limit_shared.rate_hit("mgw:fail:{ip}", 20, 60)`.
- **Redis fail policy: signature+replay = fail-CLOSED, rate-limiter = fail-OPEN.** A replay is worse than a dropped legit reply (replays are attacker traffic); a rate-limiter outage is noise, don't drop legit mail because the counter store hiccuped.
- **New sub-module `core/email/mailgun/` service ingest flow.** Inside the Celery task: (1) `SET LOCAL app.current_org_id = <org_id>` after sender-token resolution; (2) resolve sender → org → contact; (3) parse the SPF / DKIM results Mailgun already computed (see next bullet); (4) call shared `_persist_inbound_email(session, *, org_id, ...)` — refactored from `receive_email` so both OAuth and Mailgun paths use it; (5) publish `email.message_received` / `email.replied` workflow events; (6) delete the pending-inbound directory on success (or leave it for the DLQ path on failure).
- **Sender-auth is enforced — no auto-attribution on failed SPF/DKIM.** Mailgun forwards `X-Mailgun-Spf`, `X-Mailgun-Dkim-Signature` and its own eval verdicts. We persist BOTH the raw headers and structured columns `spf_result` (`pass|fail|softfail|neutral|none`) and `dkim_result` (`pass|fail|none`) on `tbl_messages`. **Policy:** if either result is `fail` AND the claimed sender email matches an existing contact via `find_contact_by_email`, we set `contact_id = NULL` on the persisted message (not the matched contact), tag the message with `spoof_suspected: true` in payload, write a `mailgun.inbound.sender_auth_failed` audit event, and skip `email.replied` workflow-event publishing. Operator sees the inbound but no automation fires and no contact is spoofed. This closes the Attacker C2 "CEO fraud" scenario.
- **`channel_message_id` for Mailgun-path uses Mailgun's delivery ID, not the sender's RFC Message-ID.** Value: `mg:{mailgun_message_id}` where `mailgun_message_id` is the Mailgun-minted per-delivery UUID from the payload (`Message-Id` field from Mailgun's own bookkeeping, not the header). Prevents Attacker M3 pre-reservation censorship: attacker can't reserve a slot in our uniqueness index by choosing their own `Message-ID`. The RFC Message-ID from headers still lands in `payload.rfc_message_id` for threading purposes only.
- **Shared helper: `_persist_inbound_email(session, *, org_id, contact_id, headers, body_text, body_html, attachments, channel_message_id, spf_result, dkim_result, source_provider, source_reference) -> Message | None`.** Refactored out of `receive_email` — OAuth callers pass their existing values; Mailgun callers pass `source_provider="mailgun"`, `source_reference={"smtp_sender_id": <uuid>, "mailgun_delivery_id": <str>}`. **Every threading DAL call inside this helper takes `org_id` explicitly** — never trusts session-scoped tenant context alone (closes Attacker C3 cross-org threading scoping). Preserves existing behavior for OAuth (unread bump, activity log, assignee notify, workflow publish) — new pytest asserts byte-identical DB output before/after refactor for OAuth path.
- **New sibling helper `find_contact_by_email(session, *, org_id, email) -> Contact | None`** in `core/contacts/data_access.py`. Does not exist today — plan-review found the assertion was wrong. Adds a lower(email)-normalized lookup scoped by org_id. Returns None if no match, single row if one match, most-recently-updated row if multiple (matches existing pattern in `find_duplicate_candidates` for tie-breaking).
- **Idempotency: partial unique index `UNIQUE(org_id, channel, channel_message_id) WHERE channel_message_id IS NOT NULL` on `tbl_messages`.** THIS INDEX AFFECTS ALL INBOUND CHANNELS (Gmail, Microsoft, WhatsApp, Meta), not just Mailgun. Migration includes a probe step that hard-fails if existing data has collisions — this is Step 0's own step so a failure doesn't block a later Mailgun-only step. Zero collisions expected in practice; if any surface, they're a pre-existing bug regardless of this track.
- **Dead-letter surface: `tbl_email_inbound_dlq`.** New table (columns: `id`, `org_id nullable`, `mailgun_delivery_id`, `pending_inbound_path`, `error_reason`, `error_details_jsonb`, `retry_count`, `created_at`, `resolved_at`). Populated when the Celery worker exhausts retries. Simple admin-only endpoint `GET /api/v1/admin/email-inbound-dlq` (Owner role only, org-scoped except for system-level unknown-recipient failures visible to platform admins). No auto-retry UI in v1; operators can `curl POST /reprocess/{id}` to hand-drive.
- **Two-phase attachment write (staging → messages/).** Attachments extracted from the pending-inbound payload land in `./storage/{org_id}/staging/{request_uuid}/` first. Only AFTER the `Message` row commits are they moved to `./storage/{org_id}/messages/{message_id}/`. Orphan-sweeper cron cleans staging > 1h + messages/ subdirs with no matching row > 24h. Closes Attacker M5 race (sweeper deleting files an in-flight ingest is about to reference).
- **Attachment MIME allowlist is EXPLICIT, `text/*` glob dropped.** Allowed: `text/plain`, `text/csv`, `image/jpeg`, `image/png`, `image/gif`, `image/webp`, `application/pdf`, `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/vnd.ms-excel`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `application/vnd.ms-powerpoint`, `application/vnd.openxmlformats-officedocument.presentationml.presentation`, `application/zip`. Everything else rejected + audited + stripped from message. `text/html` explicitly NOT allowed (inline-rendered → XSS).
- **libmagic sniff beats declared Content-Type** (already available: `python-magic` is in `api/requirements.txt`). Attacker labels `.exe` as `image/jpeg` → sniff-type fails allowlist → rejected.
- **All attachments served with `Content-Disposition: attachment`**, never `inline`. Applies to every MIME type (including PDFs, images) to prevent origin-side exploit rendering. Documented + enforced in the download endpoint. Cookieless subdomain serving is a follow-up (see open items).
- **New attachment-download endpoint.** Plan-review confirmed no `/api/v1/files/` endpoint exists today. New endpoint `GET /api/v1/messages/{message_id}/attachments/{safe_key}` under `core/conversations/router.py` (existing module). Auth: standard JWT + `org_id`-scoped (contact/message org must match caller's JWT org). Enforces `Content-Disposition: attachment` server-side. Path traversal guarded by `safe_key` regex `^[A-Za-z0-9._-]{1,255}$`.
- **Contact matching by sender email.** Uses new `find_contact_by_email`. No match → conversation created with `contact_id = NULL` and a `mailgun.inbound.no_contact_match` audit event. Auto-create-contact deliberately out of scope.
- **Auto-responder loop detection.** Ingest inspects RFC headers `Auto-Submitted`, `Precedence`, `X-Auto-Response-Suppress` — if `Auto-Submitted != "no"` (per RFC 3834), OR `Precedence: bulk|junk|list`, OR `X-Auto-Response-Suppress: All|OOF|AutoReply` — persist the message with `payload.auto_generated = true` and SKIP publishing `email.replied` / `email.message_received` workflow events. Prevents workflow-auto-response ↔ customer-vacation-reply mail loops.
- **Frontend surface: inline on the SMTP sender card** ([`app/src/app/features/user/core/settings/integrations/email-sender-card.component.ts`](APP/src/app/features/user/core/settings/integrations/email-sender-card.component.ts)). Adds a "Reply capture" section showing `in_<token>@reply.neuradigi.com` with a Copy button, plus a toggle for the per-sender `capture_replies_in_crm` opt-out. Standard amber warning banner (per memory `feedback_standard_warning_banner_pattern.md`) when `capture_replies_in_crm=false` explains "replies will land at your SMTP mailbox, not the CRM."
- **Inactive/unknown-sender inbound lands in a system-visible bucket.** Any inbound with sender `verified_at IS NULL`, `capture_replies_in_crm=false` (but somehow got captured), or `contact_id = NULL` — persist normally but flag `payload.system_review_required = true`. Frontend inbox surfaces these under a "Needs Review" filter chip visible to Owner + Admin roles. No new endpoint — reuses existing conversation list with a filter param.
- **Two-phase Mailgun setup.** Phase A (dev): free Mailgun sandbox domain (auto-created on signup, 5 whitelisted recipients, unlimited inbound) — all Steps 1–7 verified against this. Phase B (prod cutover): swap `MAILGUN_DOMAIN` env var to `reply.neuradigi.com` once DNS is added and Mailgun verifies. No code change between phases.
- **Mailgun Route configured via `api/src/app/scripts/mailgun_route_setup.py`** — one-off script (matches location of existing `seed_*.py` scripts). Explicitly uses `forward()` action, NOT `store()` (avoids SSRF via message-url fetch). Prompts for confirmation before mutating a prod-domain route from a non-prod env (guards against dev-vs-prod fat-finger, closes Absence B5). Idempotent — fetches existing routes, updates if match, creates if not.

## What this track does NOT do

- **Gmail / Microsoft OAuth Reply-To rewriting.** Their sync fetches replies natively — rewriting Reply-To would divert replies away from the mailbox the sync is watching and silently break OAuth threading. Memory `project_mailgun_inbound_scope.md` locks this.
- **Reply-compose surface** (a reply box on a conversation for the operator to reply back through the SMTP sender). REVIEW_CHECKLIST §M.14 flags this as a broader gap — Architect reviewer noted this track ships receive-only, closing half the loop. **Explicit follow-up track** — not this one, because compose is a UI-heavy scope of its own. This track proves inbound works; compose is next.
- **Custom customer domains** (`reply.customer.com`). v1 = shared `reply.neuradigi.com`. Custom domains would plug into the existing `core/email_sender_setup/` module (which already owns SPF/DKIM/DMARC verification for sending domains) — the plumbing is there, but per-org receiving-domain routing is a full follow-up.
- **Token rotation UI + audit trail.** Operators can rotate via a service function; no frontend button. Rotation invalidates all prior outbound Reply-To addresses (replies to old sends land as `unknown_recipient`).
- **Auto-create contact from unknown sender.** Belongs in a lead-capture track.
- **IMAP fallback.** No IMAP path exists; Mailgun-down means replies queue at Mailgun.
- **AI reply drafting / auto-response.** Workflows / assistant track.
- **Reply-To for auth mail** (welcome / password-reset / OTP). Uses Brevo, not `OrgSmtpBackend`. Untouched.
- **Bounce / spam / DMARC report webhooks.** Mailgun ships these as separate routes; v1 handles inbound only.
- **Cookieless subdomain for attachment serving.** Force-attachment + libmagic sniff is enough defense-in-depth for v1; cookieless subdomain is a follow-up if a real exploit surfaces.
- **Antivirus scan on attachments.** Deferred.
- **Multi-recipient Mailgun deliveries** (one Mailgun payload with two of our tokens as recipients). Reject payloads where more than one of the `To`/`Cc` addresses resolves to our inbound tokens — audit event `mailgun.inbound.multi_recipient` + drop. Rare; if a real need surfaces, it's a follow-up.
- **Delivery Status Notifications (DSN) / NDR handling.** Mail-server bounces addressed to `Return-Path` don't reach our webhook. If a misconfigured server delivers an NDR to our Reply-To, treated as auto-responder (Auto-Submitted header) → persisted, no workflow trigger.
- **HTML sanitization of inbound `body_html` in the inbox renderer.** Not this track's job — the existing inbox already renders inbound HTML. If a sanitization gap exists there (out of scope for this doc to audit), it's a cross-cutting security fix, not Mailgun-specific.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Inbound provider | **Mailgun** (Routes API + Forward action) | Sandbox tier for dev, low PAYG pricing, mature signature scheme. Postmark / SES / SendGrid all viable — Mailgun picked as the concrete choice. |
| Scope of Reply-To rewrite | **SMTP senders only** where `capture_replies_in_crm=true` | Memory `project_mailgun_inbound_scope.md` + HubSpot-parity opt-out. |
| Module location | **`core/email/mailgun/`** (parallel to `core/email/gmail/`, `core/email/microsoft/`) | Matches existing per-provider convention under the email domain module. |
| Receiving domain (prod) | **`reply.neuradigi.com`** | Sits under the existing `neuradigi.com` DNS zone. |
| Receiving domain (dev) | **Mailgun sandbox subdomain** (auto-created) | Free forever, no DNS needed. |
| Token scope | **One token per SMTP sender** — column on `tbl_email_smtp_senders` | Per-sender attribution. Polymorphic `tbl_inbound_addresses` table (Architect suggestion) rejected as YAGNI — v2 custom-domain feature doesn't need it (per-sender token at per-org domain works with a `receiving_domain` column). |
| Token format | **12-char base64url via `secrets.token_urlsafe(9)[:12]`** — `in_<12chars>@…` | 72 bits of entropy pre-slice, ~60 bits post-slice. URL-safe, human-copyable, doesn't leak sequential DB IDs. |
| Token uniqueness | **`UNIQUE` constraint** on `tbl_email_smtp_senders.inbound_token`. Retry up to 10 times on collision + metric `smtp_sender.token_collision_total`. | Belt-and-braces + observability. |
| Per-sender opt-out | **`capture_replies_in_crm BOOLEAN NOT NULL DEFAULT true`** column | HubSpot parity — small-biz owners running SMTP against Gmail app-password may want replies to land at Gmail. |
| Signature verify formula | **`hmac.new(MAILGUN_SIGNING_KEY.encode("utf-8"), (timestamp + token).encode("utf-8"), hashlib.sha256).hexdigest()`** — constant-time compare, 5-min window, replay cache. | Spelled out verbatim in the plan and step to prevent HMAC-input mistakes (Stripe-shape common bug). |
| Signing key rotation | **`MAILGUN_SIGNING_KEY` + `MAILGUN_SIGNING_KEY_PREVIOUS`** — try current, fall back to previous. | Zero-loss rotation window. |
| Redis fail policy | **Signature+replay = fail-CLOSED (reject); rate-limiter = fail-OPEN (allow through).** | Replay-window skew is attacker; limiter outage is noise. |
| Request-time constancy | **All resolution/ingest work in Celery.** Webhook path: verify → persist to disk → enqueue → 200. | Closes token-existence oracle (Attacker H2). |
| Broker-down safety | **Payload persisted to `./storage/pending-inbound/{uuid}/` BEFORE enqueue.** Cron sweeper re-enqueues pending-inbound > 5min. | Closes Absence B2 broker-down loss. |
| Rate limit | **Only on signature-verify FAILURES per IP, 20/min via `rate_hit`.** Signed traffic bypasses. | Prevents Mailgun IP-pool sharing from shedding legit mail (Attacker H1). |
| Reply-To injection point | **Inside `send_email()` in `core/conversations/adapters/email.py`.** Compute the value there, pass through the already-existing `reply_to` param to `_build_outbound_mime()`. | The `reply_to` param already exists at both layers (`send_email:229`, `_build_outbound_mime:863`). |
| Reply-To collision | **SMTP-capture is authoritative — replaces caller-supplied `reply_to`.** Original preserved in `Message.payload.original_reply_to`. | Predictable + auditable (Attacker H4). |
| Idempotency guarantee | **Partial unique index `UNIQUE(org_id, channel_message_id) WHERE channel_message_id IS NOT NULL` on `tbl_messages`.** Own migration step (Step 0) with data probe. `channel` deliberately NOT included — `tbl_messages` has no `channel` column (lives on `tbl_conversations`); provider ID formats (`mg:<uuid>`, `wamid.HB...`, RFC `<uuid@domain>`) are disjoint in practice. | Per-org index — sequenced separately so a probe failure doesn't block Mailgun steps. |
| `channel_message_id` for Mailgun path | **`mg:<mailgun_delivery_id>`** — Mailgun-minted per-delivery ID, NOT the RFC `Message-ID` header. | Prevents attacker pre-reservation censorship (Attacker M3). RFC `Message-ID` kept in `payload.rfc_message_id` for threading only. |
| Unknown recipient | **Return 200 (Celery task audits + drops).** No signal to attacker whether token exists. | Response-time constancy. |
| Inactive sender / no-contact | **Persist to org's inbox with `payload.system_review_required = true`.** Visible to Owner+Admin via existing filter chip. | Never silently drop customer replies. |
| Deleted org | **Audit `mailgun.inbound.deleted_org`, drop.** | Nothing to persist against. |
| Contact match | **New `find_contact_by_email(session, *, org_id, email)` DAL** — org-scoped, lower(email) normalized, most-recently-updated on tie. | Function doesn't exist today (plan-review corrected the assertion). |
| Sender-auth policy | **SPF-fail OR DKIM-fail + email-matches-a-contact → `contact_id=NULL` + `spoof_suspected=true` + skip workflow events.** Persist inbound so operator can inspect. | Closes CEO-fraud vector (Attacker C2). |
| Threading | **Shared `_persist_inbound_email(session, *, org_id, …)` — every threading DAL call takes `org_id` explicitly**, not session-scoped tenant context alone. | Cross-org threading safety (Attacker C3). |
| Auto-responder detection | **Inspect `Auto-Submitted`, `Precedence`, `X-Auto-Response-Suppress` headers.** Skip workflow-event publishing when detected. Persist message with `payload.auto_generated=true`. | Prevents mail loops. |
| Multi-recipient payloads | **Reject + audit** if >1 of `To`/`Cc` resolves to our inbound tokens in the same delivery. | Rare, ambiguous — safer to reject than route to one arbitrarily. |
| Attachment storage | **Two-phase: `./storage/{org_id}/staging/{request_uuid}/` → moved to `./storage/{org_id}/messages/{message_id}/` on commit.** Per-file 10 MB, per-message 25 MB, sniff-then-allowlist MIME. | Race-safety + bomb defense + spoof defense. |
| Attachment MIME allowlist | **Explicit list** (see "What this track does" section). `text/html` NOT allowed. | Drop `text/*` glob (Attacker H3). |
| Attachment serving | **New endpoint `GET /api/v1/messages/{message_id}/attachments/{safe_key}` under `core/conversations/router.py`.** JWT + org-scoped. `Content-Disposition: attachment` for all types. | No `/api/v1/files/` endpoint exists today (plan-review corrected the assertion). |
| DLQ | **New table `tbl_email_inbound_dlq`** — Celery exhausted-retry payloads. Admin-only inspect endpoint. | Closes silent-loss on repeated failure (Absence B1). |
| Orphan-sweeper cadence | **Daily beat entry. Staging cleanup > 1h; messages/ orphans > 24h.** Two-phase attachment write means staging can be cleaned aggressively. | Closes race + orphan disk bloat. |
| Route action | **`forward()`, NOT `store()`** | Avoids SSRF via message-url fetch. |
| Route-setup script location | **`api/src/app/scripts/mailgun_route_setup.py`** — matches existing seed-scripts location | Plan-review corrected `API/scripts/` → `api/src/app/scripts/`. |
| Route-setup dev-vs-prod safeguard | **Script prompts for confirmation when the resolved `MAILGUN_DOMAIN` is a production-looking domain and `config.env` is not the prod env file.** | Guards against fat-fingering a sandbox route into prod (Absence B5). |
| Env var split | **`MAILGUN_DOMAIN`** (Mailgun's config domain) + **`INBOUND_EMAIL_DOMAIN`** (appended to Reply-To). Same value today; split so custom-domain v2 can diverge. | Split-early. |
| Region | **US** | Default. EU requires new Mailgun domain — revisit only if EU-resident client demands. |
| Health-check endpoint | **`GET /api/v1/webhooks/mailgun/inbound/health`** — no auth, no signature. | Ops + Mailgun URL validator. |
| Backfill migration idempotency | **Per-row token generation is idempotent — WHERE `inbound_token IS NULL` only.** Partial-crash retry regenerates only unfilled rows. | Zero-downtime + resumable (Absence B6). |
| Frontend test runner | **Karma** — the existing runner (`ng test`). | Plan-review corrected Jest assumption. |

## Cases the plan must handle

*Per PLANNING_RULES §4. Two-user, unfinished-work, orphan-record, caller-assertion cases.*

**Concurrency & timing:**

1. **Same Mailgun delivery arrives twice** (retry after our 500). Signature valid; `mg:<delivery_id>` already in unique index → second insert IntegrityError, task returns idempotent.
2. **Two Mailgun deliveries land within 10ms** for same token. Both enqueue; unique index catches second on insert.
3. **Attacker replay: captured `(timestamp, token, sig)` re-posted.** Redis replay cache holds token 10min → 401. Beyond window, timestamp check rejects.
4. **Clock skew: our server 5min ahead of Mailgun.** Legit delivery timestamp fails `abs(now-ts) > 300` → 401 + audit. Tolerance widens to 600s only if false-positives seen (documented).
5. **Broker (Redis/RabbitMQ) is DOWN when the task is enqueued.** Payload already on disk under `pending-inbound/{uuid}/`. Webhook returned 200 (payload is safe). Cron sweeper picks the directory after 5min and re-enqueues when broker recovers.
6. **Redis DOWN during signature verify (replay cache lookup fails).** Fail-CLOSED → 500 to Mailgun → Mailgun retries. When Redis recovers, next retry lands. No lost mail, no accepted replay.
7. **Redis DOWN during rate-limiter check on a failed-signature request.** Fail-OPEN → request proceeds (which then 401s on signature anyway). Attacker can't exploit — signature still gates.
8. **Two admins in the same org create SMTP senders concurrently.** Each gets a distinct token (generated inside insert transaction; unique constraint catches collision, regenerate — up to 10 tries).
9. **Admin deletes SMTP sender while a Mailgun webhook is mid-flight for that token.** Deletion is manual only; the plan requires `?force=true` + admin role + re-auth if any inbound occurred in last 30 days. During the mid-flight window, ingest's sender-lookup in the Celery task returns None → `mailgun.inbound.sender_deleted_after_route` audit event + drop.
10. **Two admins concurrently deactivate + delete the same sender.** DB row-lock at the service layer serializes; whichever transaction commits first wins. Second admin sees 409 on `If-Match`-ETag (existing pattern from workflow-scheduling).

**Data lifecycle:**

11. **Sender is deactivated (`verified_at = NULL`) between outbound send and reply.** Reply routes (token still exists) → persist + audit + `system_review_required=true`. Operator sees under "Needs Review" filter.
12. **Sender `capture_replies_in_crm` toggled to `false` between outbound send and reply.** Reply still routes (token still exists) — the toggle only affects FUTURE outbound. Existing outbound already has our Reply-To in the wild. Persist as normal.
13. **Token rotated.** Old token invalidated (row overwritten — not a separate `revoked_at` in v1 to keep it simple). Replies to prior sends land as `unknown_recipient` audit.
14. **Contact deleted between outbound send and reply.** `find_contact_by_email` returns None → `contact_id = NULL` + audit.
15. **Contact merged into another contact.** Existing merge cascade updates FK references. A merged-away email may still match via the surviving contact's primary_email; if not, NULL + audit.
16. **Two contacts with same email in one org** (rare, but the DB permits it). `find_contact_by_email` returns most-recently-updated. Audit event logs the tie-break for operator visibility (`mailgun.inbound.contact_tie_break`).
17. **Same customer email exists in Org A AND Org B**, replies to Org A's token. Token resolves to Org A → `find_contact_by_email(org_id=A, email=…)` scopes to Org A. Cross-org contamination impossible by design.
18. **Conversation deleted while reply in flight.** Threading falls back to contact-latest → creates new conversation. No orphan reply.
19. **Org soft-deleted / suspended.** Celery task checks org status → audit `mailgun.inbound.org_suspended` + drop.
20. **Org hard-deleted.** Sender row CASCADE-gone → token lookup misses → `unknown_recipient`.

**Attachment edge cases:**

21. **Attachment upload to staging succeeds, message insert fails.** Rollback + staging cleanup by orphan sweeper (staging > 1h). No corruption of `messages/`.
22. **Attachment total > 25 MB.** Reject at parse → audit + strip attachments → persist message text with `attachment_stripped_reason: size_exceeded`.
23. **Attachment MIME is `application/x-msdownload`.** Allowlist rejects at sniff time. Audit + strip.
24. **Attachment declared `image/jpeg` but sniffs as `application/x-executable`.** libmagic sniff wins → rejected.
25. **`.html` attachment.** Rejected — `text/html` not in allowlist.
26. **Attachment filename `../../etc/passwd`.** `pathlib` sanitisation strips path separators → safe.
27. **Zip bomb (10 KB → 4 GB uncompressed).** We do NOT decompress. Stored as-is under 10MB cap. Served with `Content-Disposition: attachment` — user downloads at own risk. Antivirus deferred.
28. **Two attachments named `image.png` in one message.** Disambiguate: `image.png`, `image-2.png`.

**Threading & spoof:**

29. **Reply is well-formed, SPF+DKIM pass.** Persist with `contact_id` from match, publish workflow events.
30. **Reply has `From: ceo@acme.com`, SPF FAIL.** Persist with `contact_id=NULL`, `spoof_suspected=true`, `mailgun.inbound.sender_auth_failed` audit, no workflow event. Operator sees message under Needs Review.
31. **Reply has DKIM fail but SPF pass** (partial auth). Same as full-fail — either failure is enough to skip auto-attribution.
32. **Reply from a different email than the outbound `To:`.** `find_contact_by_email` misses → NULL contact + audit. Operator can manually link.
33. **Attacker copies Message-ID from a real outbound, spoofs an inbound with `In-Reply-To: <that-id>` to a different org's token.** Token resolves to Org B; threading query is `_persist_inbound_email(org_id=B, …)` — searches Org B messages only, no match, falls to contact-latest in Org B. No cross-org contamination.
34. **Attacker sends inbound with `Message-ID: <spam-Message-ID>` trying to pre-reserve slot.** Idempotency key is `mg:<mailgun_delivery_id>` (Mailgun-minted), NOT the RFC Message-ID. Pre-reservation impossible.
35. **Auto-responder loop: customer vacation-reply.** `Auto-Submitted != no` OR `Precedence: bulk` → persisted with `payload.auto_generated=true`, workflow-event publish skipped. Loop broken.
36. **DSN / NDR delivered to our Reply-To.** Same as auto-responder — headers usually indicate `Auto-Submitted` or `Return-Path` variants. Treated as auto-generated.
37. **Payload's `To`/`Cc` includes TWO of our inbound tokens.** Reject + `mailgun.inbound.multi_recipient` audit + drop.

**Configuration & assertions:**

38. **`MAILGUN_SIGNING_KEY` unset in env.** Webhook rejects ALL with 401 + `mailgun.webhook.signing_key_missing` error log. Fail-closed.
39. **`MAILGUN_SIGNING_KEY_PREVIOUS` set during rotation.** Verify tries current, falls back to previous. Both windows accept.
40. **`INBOUND_EMAIL_DOMAIN` differs from `MAILGUN_DOMAIN`.** Explicit for future custom-domain. Reply-To uses `INBOUND_EMAIL_DOMAIN`; route setup uses `MAILGUN_DOMAIN`. Same value today.
41. **Operator forgets to create Mailgun Route.** Outbound Reply-To goes out; Mailgun accepts inbound but has no forward target → bounces at Mailgun. Documented in Step 8; "no inbound in 7 days for orgs with active SMTP senders" health check is a follow-up.
42. **Route-setup script run against prod Mailgun from dev env by mistake.** Script's prod-domain safeguard prompts for confirmation before mutating a prod-looking domain from a non-prod env.
43. **Backfill migration crash after some senders got tokens.** Retry regenerates only WHERE `inbound_token IS NULL` — idempotent, resumable.
44. **Celery worker SIGKILL'd during attachment write.** Staging directory left behind; orphan sweeper picks up after 1h. Message never inserted → no half-committed state.
45. **DLQ fills up faster than operators can inspect.** Table has an index on `created_at`; admin endpoint paginates. No auto-purge in v1; ops concern for retention track.

**Attacker lens:**

46. **Attacker POSTs random JSON.** No signature → 401. Fail counter increments; 20 fails in 60s from same IP → shed at rate limiter.
47. **Attacker POSTs valid signature with fabricated token.** Signature verifies; Celery task's sender lookup misses → 200 (already returned to Mailgun) + `unknown_recipient` audit at system level (not visible to any tenant, prevents PII leak).
48. **Attacker POSTs valid signature with real captured token + spoofed sender email.** SPF/DKIM fail → NULL contact + audit + no workflow trigger. Message visible to Owner+Admin under Needs Review; can be manually reviewed.
49. **Attacker enumerates tokens via SMTP to Mailgun.** Response time is constant (all work in Celery, request path only verifies + writes to disk). No timing oracle.
50. **Attacker POSTs 10K signed-fabricated messages.** Signature-fail rate-limit doesn't apply (they're signed). Volume-shed at Mailgun's own ingress + our disk-write throughput. Additional DoS shielding is a follow-up.
51. **Mass-assign attacker tries `PATCH /email-senders/{id}` with `inbound_token: "chosen"`.** Schema (`EmailSmtpSenderUpdate`) doesn't expose `inbound_token` — rejected.
52. **Admin `?force=true` delete during CSRF-phish.** Re-auth (password confirm modal) required in addition to role check.
53. **PII leak via unknown-recipient audit.** System-level audit only, invisible to tenants. Sender emails in these events don't cross tenants.
54. **SSRF via Mailgun `store()` mode.** N/A — we explicitly use `forward()`. Route-setup script asserts this.

## Tests (named-before-code)

**Migration + backfill (Step 0 + Step 1):**

- `test_step0_migration_partial_unique_index_created`
- `test_step0_migration_probe_hard_fails_on_channel_message_id_collision`
- `test_step0_migration_probe_passes_on_clean_data`
- `test_step1_migration_adds_inbound_token_column`
- `test_step1_migration_adds_capture_replies_in_crm_column_default_true`
- `test_step1_migration_backfills_existing_smtp_senders`
- `test_step1_backfill_idempotent_on_partial_crash_retry`
- `test_step1_migration_down_removes_columns`
- `test_step1_migration_adds_spf_dkim_columns_on_messages`
- `test_step1_migration_creates_tbl_email_inbound_dlq`

**Token generation:**

- `test_token_is_12_chars_urlsafe_base64`
- `test_token_generation_retries_up_to_10_on_collision`
- `test_token_collision_metric_emitted_on_retry`
- `test_token_uniqueness_enforced_by_constraint`

**find_contact_by_email:**

- `test_find_contact_by_email_returns_none_when_no_match`
- `test_find_contact_by_email_returns_single_match`
- `test_find_contact_by_email_returns_most_recently_updated_on_tie`
- `test_find_contact_by_email_lowercases_input`
- `test_find_contact_by_email_scoped_by_org_id`

**Reply-To injection:**

- `test_reply_to_injected_when_smtp_backend_and_capture_true`
- `test_reply_to_not_injected_when_smtp_backend_and_capture_false`
- `test_reply_to_not_injected_when_oauth_gmail_backend`
- `test_reply_to_not_injected_when_oauth_microsoft_backend`
- `test_reply_to_format_matches_in_underscore_token_at_domain`
- `test_reply_to_replaces_caller_supplied_reply_to`
- `test_reply_to_preserves_original_in_payload_metadata`
- `test_reply_to_uses_INBOUND_EMAIL_DOMAIN_env_not_MAILGUN_DOMAIN`

**Webhook signature:**

- `test_webhook_rejects_missing_signature_header`
- `test_webhook_rejects_bad_signature_returns_401`
- `test_webhook_accepts_valid_signature_returns_200`
- `test_webhook_signature_input_is_timestamp_concat_token_exactly` (byte-sequence assertion)
- `test_webhook_signature_verify_uses_constant_time_compare`
- `test_webhook_rejects_timestamp_older_than_5min_returns_401`
- `test_webhook_rejects_timestamp_in_future_by_more_than_5min`
- `test_webhook_replay_token_rejected_within_10min_window`
- `test_webhook_replay_token_accepted_after_10min_window`
- `test_webhook_signing_key_missing_rejects_all_returns_401`
- `test_webhook_fallback_to_previous_signing_key_during_rotation`
- `test_webhook_previous_key_unset_falls_through_to_normal_reject`
- `test_webhook_rate_limit_only_on_signature_failures_not_signed`
- `test_webhook_redis_down_signature_check_fails_closed`
- `test_webhook_redis_down_rate_limiter_fails_open`
- `test_webhook_request_time_constant_regardless_of_token_validity`

**Payload persistence & DLQ:**

- `test_webhook_persists_payload_to_pending_inbound_before_enqueue`
- `test_webhook_returns_200_after_disk_write`
- `test_cron_sweeper_reenqueues_pending_inbound_older_than_5min`
- `test_worker_exhausted_retries_write_to_dlq_table`
- `test_dlq_endpoint_owner_only_returns_403_for_admin`
- `test_dlq_reprocess_re_enqueues_and_marks_resolved`

**Ingest resolution:**

- `test_ingest_resolves_org_from_inbound_token`
- `test_ingest_unknown_recipient_returns_audit_system_level_not_tenant`
- `test_ingest_deleted_org_audits_and_drops`
- `test_ingest_suspended_org_audits_and_drops`
- `test_ingest_inactive_sender_persists_with_system_review_flag`
- `test_ingest_capture_false_sender_still_ingests_existing_replies`
- `test_ingest_sets_rls_context_before_dbwrite`
- `test_ingest_multi_recipient_payload_rejected_with_audit`

**Sender auth (SPF/DKIM):**

- `test_ingest_spf_pass_dkim_pass_attributes_to_contact`
- `test_ingest_spf_fail_matching_contact_sets_null_contact_and_flags`
- `test_ingest_dkim_fail_matching_contact_sets_null_contact_and_flags`
- `test_ingest_spf_fail_no_matching_contact_persists_normally`
- `test_ingest_auth_fail_skips_email_replied_workflow_event`
- `test_ingest_persists_spf_and_dkim_columns_on_message`

**Auto-responder:**

- `test_ingest_auto_submitted_yes_flags_auto_generated`
- `test_ingest_precedence_bulk_flags_auto_generated`
- `test_ingest_x_auto_response_suppress_flags_auto_generated`
- `test_ingest_auto_generated_skips_workflow_events`

**Threading (shared helper):**

- `test_persist_helper_takes_org_id_explicitly`
- `test_persist_helper_threading_dal_calls_carry_org_id`
- `test_reply_via_in_reply_to_threads_correctly`
- `test_reply_missing_headers_falls_back_to_contact_latest`
- `test_reply_no_prior_conversation_creates_new`
- `test_oauth_receive_email_byte_identical_output_after_refactor`
- `test_cross_org_message_id_never_threads_to_wrong_org`

**Idempotency:**

- `test_mailgun_channel_message_id_uses_mg_prefix_and_delivery_id`
- `test_attacker_cannot_reserve_channel_message_id_via_rfc_message_id`
- `test_duplicate_delivery_second_insert_rejected_by_partial_index`
- `test_concurrent_deliveries_only_one_row_persists`

**Attachments:**

- `test_attachment_written_to_staging_first`
- `test_attachment_moved_to_messages_only_after_commit`
- `test_attachment_metadata_appended_to_jsonb`
- `test_attachment_over_10mb_rejected_and_stripped`
- `test_attachment_total_over_25mb_stripped_message_preserved`
- `test_attachment_mime_not_in_allowlist_rejected`
- `test_attachment_text_html_rejected_from_allowlist`
- `test_attachment_libmagic_sniff_wins_over_declared_content_type`
- `test_attachment_filename_path_traversal_sanitised`
- `test_attachment_filename_collision_gets_numeric_suffix`
- `test_attachment_staging_orphan_cleaned_after_1h`
- `test_attachment_messages_orphan_cleaned_after_24h`
- `test_attachment_sweeper_does_not_race_in_flight_ingest`
- `test_attachment_download_endpoint_enforces_jwt_and_org_scope`
- `test_attachment_download_endpoint_forces_content_disposition_attachment`
- `test_attachment_download_safe_key_regex_rejects_path_traversal`

**Cross-org isolation:**

- `test_cross_org_token_never_resolves_to_wrong_org`
- `test_cross_org_mass_assign_of_inbound_token_rejected_by_schema`
- `test_cross_org_contact_lookup_scoped_by_org_id`
- `test_unknown_recipient_audit_not_visible_to_any_tenant`

**Frontend:**

- `test_sender_card_response_includes_inbound_reply_address`
- `test_sender_card_response_includes_capture_toggle`
- `test_sender_card_response_never_leaks_signing_key_or_api_key`
- `test_frontend_renders_reply_address_with_copy_button` (Karma)
- `test_frontend_capture_toggle_shows_warning_banner_when_false` (Karma)

**Route setup script:**

- `test_route_setup_script_uses_forward_action_not_store`
- `test_route_setup_script_creates_route_when_absent`
- `test_route_setup_script_updates_route_when_present`
- `test_route_setup_script_prompts_confirmation_prod_domain_from_non_prod_env`
- `test_route_setup_script_idempotent`

**Force-delete + re-auth:**

- `test_sender_delete_without_force_flag_rejected_if_recent_inbound`
- `test_sender_delete_with_force_flag_requires_password_reauth`

## Discovery reference (corrected against actual repo)

**Reused primitives (verified):**

- [`send_email`](API/src/app/core/conversations/adapters/email.py#L229) already accepts `reply_to: str | None`. Change is 3 lines to compute + pass.
- [`_build_outbound_mime`](API/src/app/core/conversations/adapters/email.py#L863) — same, `reply_to` param already present.
- [`receive_email`](API/src/app/core/conversations/adapters/email.py#L574) — refactored to call new shared `_persist_inbound_email`. OAuth callers unchanged, output byte-identical.
- [`extract_thread_keys`, `extract_message_id`](API/src/app/core/conversations/adapters/email_threading.py) — used verbatim.
- [Meta webhook auth pattern](API/src/app/core/integrations/meta/webhook.py) — HMAC + constant-time + audit-on-fail + enqueue-then-200.
- [`shared.rate_limit_shared.rate_hit`](API/src/app/shared/rate_limit_shared.py) — used for signature-failure rate limit. No middleware class; direct helper call.
- Redis pattern uses `redis.asyncio` client, key prefix convention (`rlx:` for rate-limit, `mgw:` for Mailgun webhook). No new wrapper needed.
- [`audit.log`](API/src/app/core/__init__.py) — audit event conventions.
- [StorageBackend abstraction](API/src/app/shared/storage/) — attachment writes.
- [`tbl_messages.attachments` JSONB](API/src/app/core/conversations/models.py) — schema-free field. WhatsApp uses a different shape (`type`, `id`, `sha256`), so Mailgun defines its own shape (`filename`, `size`, `content_type`, `storage_key`, `sniffed_content_type`) — no cross-channel expectation.
- `python-magic` — already in `api/requirements.txt` for MIME sniff.
- [`email_sender_setup/`](API/src/app/core/email_sender_setup/) — existing SPF/DKIM/DMARC verification module; NOT used in this track but the natural home for future custom-domain (v2).

**New primitives created:**

- `find_contact_by_email(session, *, org_id, email)` in `core/contacts/data_access.py` — did not exist; plan-review corrected.
- `GET /api/v1/messages/{message_id}/attachments/{safe_key}` in `core/conversations/router.py` — no public file-download endpoint exists today.

**Competitor benchmarks (interim, unsourced — `PRODUCT_BRIEF.md` does not exist):**

- **HubSpot Connected Inbox** — for shared-team addresses, rewrites Reply-To to per-team-inbox capture address; for personal IMAP inboxes, does NOT rewrite (relies on IMAP pull). **We match** with per-sender `capture_replies_in_crm` toggle.
- **Zoho SalesInbox** — per-user reply aliases at `<hash>@salesinbox.zoho.com`. Same shape as ours. **We match** (per-sender vs per-user is a scope choice).
- **Pipedrive Smart Email BCC** — different model: per-user BCC address the user CCs on outbound from their own mailbox. Doesn't apply — we're not intercepting the user's own mailbox; we're providing send + capture as one flow.
- **Front** — AWS SES Inbound + per-inbox alias. **We match** shape.
- **Close.io** — SES Inbound + per-sender token. **We match**.

## Files touched

**Backend:**

- `core/email_senders/models.py` — add `inbound_token`, `capture_replies_in_crm` columns.
- `core/email_senders/data_access.py` — add `find_by_inbound_token`.
- `core/email_senders/service.py` — token generation, expose reply-address in response, toggle endpoint.
- `core/email_senders/schemas.py` — `InboundReplyAddress` sub-schema, toggle schema.
- `core/email_senders/router.py` — response includes `inbound_reply_address`; PATCH endpoint for `capture_replies_in_crm`.
- `core/contacts/data_access.py` — NEW `find_contact_by_email`.
- `core/conversations/adapters/email.py` — 3-line Reply-To computation in `send_email`; refactor `receive_email` to use shared `_persist_inbound_email`; add `_persist_inbound_email` (with `org_id` explicit + `spf_result` + `dkim_result` + `source_provider` + `source_reference` params).
- `core/conversations/adapters/email_threading.py` — no change (helpers reused verbatim).
- `core/conversations/models.py` — add `spf_result`, `dkim_result` columns on `Message`.
- `core/conversations/router.py` — NEW `GET /messages/{id}/attachments/{safe_key}` endpoint.
- `core/email/mailgun/__init__.py`, `schemas.py`, `router.py`, `service.py`, `data_access.py`, `tasks.py` — new sub-module (5 layered files + tasks worker).
- `core/email/mailgun/orphan_cleanup.py` — daily orphan sweep (staging + messages/).
- `core/email/mailgun/pending_inbound_sweeper.py` — 5-min re-enqueue for broker-down.
- `core/email/mailgun/dlq.py` — DLQ table access + admin endpoint.
- `core/admin/router.py` (or nearest existing admin router) — DLQ inspect + reprocess endpoints.
- `main.py` — register `mailgun.router` under `/api/v1/webhooks`.
- `shared/celery_config.py` — beat entries for orphan sweep + pending-inbound sweep.
- Alembic migration Step 0: `tbl_messages` partial unique index + collision probe.
- Alembic migration Step 1: `tbl_email_smtp_senders.inbound_token` + `capture_replies_in_crm` + backfill; `tbl_messages.spf_result` + `dkim_result`; `tbl_email_inbound_dlq` table.
- `secrets.enc.env` — `MAILGUN_API_KEY`, `MAILGUN_SIGNING_KEY`, `MAILGUN_SIGNING_KEY_PREVIOUS` (empty by default).
- `config.env` — `MAILGUN_DOMAIN`, `INBOUND_EMAIL_DOMAIN`, `MAILGUN_WEBHOOK_URL`.
- `api/src/app/scripts/mailgun_route_setup.py` — one-off Route-creation script.
- `pyproject.toml` — no new deps (python-magic already present).

**Frontend:**

- `features/user/core/settings/integrations/email-sender-card.component.{ts,html}` — Reply capture panel + capture toggle + warning banner.
- `features/user/core/settings/integrations/email-senders.service.ts` — parse new response fields, PATCH toggle.
- `features/user/core/settings/integrations/models.ts` — types.
- `features/user/core/conversations/message-attachment.component` (if exists — TBD in Step 6 discovery) — hook up new download endpoint URL. Fallback: existing attachment renderer already renders JSONB metadata; only the download URL construction changes.

**Docs / runbook:**

- `tasks/mailgun-inbound/mailgun-setup-runbook.md` — Step 8's operator guide.

## Step index

| # | Title | Status | Files | Effort |
|---|---|---|---|---|
| 0 | [Migration: partial unique index on `tbl_messages` + collision probe (per-org prereq)](step-0-messages-dedup-index.md) | **COMPLETED** (2026-09-02, migration `0214` applied against prod; 685 existing messages passed probe) | 3 (migration + model + tests) | ~0.25 day |
| 1 | [Backend: `inbound_token` + `capture_replies_in_crm` columns + SPF/DKIM columns + DLQ table + backfill + `find_contact_by_email`](step-1-backend-schema-and-dal.md) | **COMPLETED** (2026-09-02, migration `0215` applied against prod; 2 existing SMTP senders backfilled with tokens; DLQ table live) | 10 | ~0.5 day |
| 2 | [Backend: 3-line Reply-To injection in `send_email` + capture toggle service + test suite](step-2-backend-reply-to-injection.md) | **COMPLETED** (2026-09-02, `_mailgun_reply_to_for` helper + `PATCH /email-senders/smtp/{id}/capture-toggle` + `INBOUND_EMAIL_DOMAIN` set to sandbox in `config.env`; full app tree loads clean) | 6 | ~0.25 day |
| 3 | [Backend: `core/email/mailgun/` module — webhook + signature + payload-to-disk + Celery enqueue + replay cache + key rotation](step-3-backend-webhook-and-signature.md) | **COMPLETED** (2026-09-02, `POST /api/v1/webhooks/mailgun/inbound` live, HMAC + replay cache + payload-to-disk + Celery enqueue wired; task stub in place for Step 4) | 8 | ~0.75 day |
| 4 | [Backend: ingest — token resolve + SPF/DKIM enforcement + auto-responder detection + shared `_persist_inbound_email` refactor + threading org-scoping](step-4-backend-ingest-and-shared-helper.md) | **COMPLETED** (2026-09-02, shared helper extracted + OAuth `receive_email` refactored + Mailgun task body: token→sender→org + SPF/DKIM enforcement + auto-responder detection + multi-recipient guard + DLQ) | 5 | ~1 day |
| 5 | [Backend: attachments — allowlist + libmagic sniff + two-phase staging→messages/ write + download endpoint + orphan-sweepers + DLQ admin endpoint](step-5-backend-attachments-and-dlq.md) | **COMPLETED** (2026-09-02, attachments live with allowlist+sniff+size caps, `GET /api/v1/messages/{id}/attachments/{key}` auth-gated force-download endpoint, Owner-only DLQ admin endpoints, orphan sweepers) | 8 | ~0.75 day |
| 6 | [Frontend: Reply capture panel + capture toggle + warning banner + attachment download URL](step-6-frontend-reply-address-panel.md) | Pending | 4 | ~0.5 day |
| 7 | [Mailgun setup — signup + sandbox smoke + Route script + end-to-end verification](step-7-mailgun-setup-and-sandbox-smoke.md) | Pending | 2 (docs+script) | ~0.5 day (blocked on Mailgun account) |
| 8 | [Production cutover — `reply.neuradigi.com` DNS + prod verify + runbook + signing-key-rotation drill](step-8-production-cutover.md) | Pending | 1 (runbook) | ~0.25 day (blocked on DNS) |

**Total: 9 steps, ~4.75 days active dev + Mailgun/DNS wait time.**

## Sequencing — why this order matters

- **Step 0 first, independent** — the cross-channel dedup index prereq. If the collision probe hard-fails, we fix data issues before any Mailgun step. Ships even if Mailgun is later scrapped.
- **Step 1 (schema)** ships every column/table needed by later steps + the new `find_contact_by_email` DAL.
- **Step 2 (Reply-To injection)** ships "outbound is inbound-capable" milestone. Replies bounce (no Mailgun yet) but the header is in the wild.
- **Step 3 (webhook + signature + persistence)** ships an endpoint that accepts, verifies, persists-to-disk, enqueues. Doesn't ingest yet.
- **Step 4 (ingest + shared helper + auth policy)** persistence works end-to-end. This is the biggest step; SPF/DKIM enforcement + refactored `_persist_inbound_email` + auto-responder detection all belong together because they share the persistence codepath.
- **Step 5 (attachments + DLQ)** extends Step 4 with binary-safe handling + failure surface. Attachments deliberately after the text-only Step 4 so bomb defense is reviewed in isolation.
- **Step 6 (frontend)** independent of Steps 3–5 but sequenced after so operators only see the address once plumbing is live.
- **Step 7 (Mailgun setup + sandbox smoke)** end-to-end against real Mailgun. Blocks on account creation.
- **Step 8 (prod cutover)** blocks on DNS.

**Recommended deploy sequence:**

1. Step 0 alone to staging + prod — cross-channel prereq, verify no data breaks.
2. Steps 1–2 to staging — verify Reply-To lands.
3. Steps 3–5 to staging — verify sandbox end-to-end.
4. Step 6 to staging — verify frontend.
5. Step 7 smoke.
6. Steps 0–6 to prod.
7. Step 8 — flip `MAILGUN_DOMAIN`, DNS goes live, prod verify.

## Reverse / rollback

- Every migration has working `downgrade`.
- Post-Step 2: unset `INBOUND_EMAIL_DOMAIN` → injection short-circuits; replies bounce at sender's ISP as they did before.
- Post-Step 5: disable Mailgun beat entries + unregister `mailgun.router` in main.py — webhook 404s, no ingest.
- Post-Step 8: Mailgun Route pointed at sink → inbound stops. Outbound Reply-To stays harmless.
- **Semantic irreversibility (Absence E8):** replies to mails sent while the feature was live continue landing at `unknown_recipient` after downgrade — audit-only, no delivery loss.

## Rules & conventions

- **10 non-negotiable rules (CLAUDE.md):** all new schema is `org_id`-scoped via SMTP-sender FK; every query filters `org_id`; RLS via `SET LOCAL app.current_org_id` in Celery. No `core/` → `packs/` imports. No TODOs.
- **Router → Service → DAL:** webhook router → service (owns transactions) → data_access (pure SQL).
- **Pin-tests:** `test_table_name_convention.py` (new `tbl_email_inbound_dlq` follows `tbl_` prefix) and `test_layered_architecture_convention.py` (mailgun sub-module follows 5-file layout).
- **Alembic revision ID ≤ 32 chars** (memory `feedback_alembic_revision_id_length.md`).
- **Prettier on write** for any Angular file (memory `feedback_prettier_on_write.md`).
- **Migrations run inline** via `API\run.cmd upgrade` before stop-and-report (memory `feedback_execute_migrations_inline.md`).
- **DB efficiency:** token lookup uses UNIQUE index; message dedup via partial index; no N+1 in ingest (contact + sender + org resolved before writes).
- **`reusable` lives in `shared/`** (memory `feedback_reusable_code_lives_in_shared.md`): `_persist_inbound_email` lives in `core/conversations/adapters/email.py` (channel-specific), NOT in `shared/`.
- **Standard warning banner pattern** (memory `feedback_standard_warning_banner_pattern.md`) — the capture-toggle warning uses the amber banner class.
- **Karma frontend tests** (`ng test`) — not Jest.

## Open items (deferred, not blocking)

1. **Cookieless subdomain for attachment serving** (e.g., `files-usercontent.neuradigi.com`) — force-attachment + libmagic sniff is enough defense-in-depth for v1; revisit if exploit surfaces.
2. **Antivirus / ClamAV scan on attachments** — deferred.
3. **Bounce / spam / DMARC report webhook processing** — Mailgun's separate routes.
4. **Custom customer domains** (`reply.customer.com`) — plugs into existing `core/email_sender_setup/` module.
5. **Token rotation UI + `revoked_at` history** — v1 is code-only.
6. **Auto-create contact from unknown sender** — belongs in lead-capture track.
7. **AI reply drafting / auto-response** — workflow track.
8. **"No inbounds in N days" passive health monitor** — for mis-configured routes.
9. **Mailgun EU region support** — swap domain + per-org region column.
10. **Postmark / SES / SendGrid alternative providers** — behind an `InboundProvider` protocol; not needed until a second provider is picked.
11. **Reply-compose surface** (REVIEW_CHECKLIST §M.14) — table-stakes gap in the broader product; not this track.
12. **DLQ retention policy + auto-purge** — v1 has no auto-purge.
13. **Audit-events retention model** — cross-cutting concern outside this track.
14. **Message-ID scoping revisit** — RFC Message-IDs are globally unique via `<uuid>@furnicrm.app` today; the org-scoping in threading protects us, but a follow-up could make Message-IDs org-attributed for defense-in-depth.
