# Email Inbound Forwarding — `f-<token>` + forwarding wizard

Accept **customer-forwarded mail** into the CRM via `f-<token>@in.karmcrm.com`. Customer sets a forwarding rule at their own mail provider (Gmail, Outlook, custom) pointing at our address; every inbound to that customer's support mailbox lands as a CRM conversation. This is the **primary-inbound** counterpart to the mailgun-inbound track's **reply-capture** flow.

**Status:** Pending — plan drafted 2026-09-21. Depends on Track 1 (endpoint abstraction). Discovery required — HubSpot / Front / Missive forwarding-wizard flows + Mailgun Routes API multi-address matching.

## Why this track exists

The shipped mailgun-inbound track captures **replies to mail we sent** — a customer replies to `in_<token>@reply.karmcrm.com`, it lands in their conversation. That's half the loop.

The other half is: a customer emails `support@acme.com` (their own mailbox at their own provider). Today, nothing captures it. The Prativani spec calls this the `f-<token>` model:

> Customer's mailbox forwards `support@theircompany.com` → `f-<token>@in.<domain>` via their provider's forwarding rule. The routing address is the SNS receipt.recipients, never the To: header (the To: still shows the customer's original address because it's forwarded mail).

Same principle for Mailgun — the Routes API's `recipient` matcher captures `f-<token>@in.karmcrm.com` regardless of what `To:` header the customer's mail shows. This unlocks:

- **Full inbox** — every mail to their support address becomes a CRM conversation, not just replies to CRM outbound.
- **Zero migration cost for the customer** — one forwarding rule at their provider; no MX changes, no domain claim.
- **Same threading model** — RFC `Message-ID` / `In-Reply-To` chain works identically; new conversation on first-touch, existing conversation on reply.

## What this track does

- **New endpoint type `forwarded_address`** on `tbl_channel_endpoints` (Track 1) + `forwarding_token` column population on `tbl_email_endpoint_details`. Token shape: `f-<12chars>` (12-char base64url via `secrets.token_urlsafe(9)[:12]`, ~72 bits pre-slice), separate from Track 1's `reply_token` column but on the same detail row (so an endpoint can carry both a forwarding token AND a reply token — future case: verified own-domain that both sends and receives).
- **Mailgun Route created per-org (or per-endpoint) via `f-.+@in.karmcrm.com` catch-all → forward to our webhook.** The shipped mailgun-inbound route already catches all mail to the inbound domain; extend the ingest task to distinguish `in_<token>@` (reply-capture, existing) vs `f-<token>@` (forwarded-address, new) by local-part prefix.
- **New POST body handling in existing Mailgun webhook.** No new endpoint URL — existing `POST /api/v1/webhooks/mailgun/inbound` handles both prefixes. Celery task's token-resolve step: parse `recipient` local-part → `f-*` → look up `find_by_forwarding_token()` from Track 1 DAL → `endpoint_type` should be `forwarded_address`. Existing gates (signature, replay cache, size, auto-submitted, SPF/DKIM, attachment allowlist) apply identically.
- **Threading + contact matching differs from reply-capture.** Reply-capture: sender is a known contact (matched via SPF/DKIM-authed From). Forwarded-address: sender is an **unknown** third party emailing our customer's support address. Ingest treats this as **primary inbound**:
  - `From:` is a new contact (or existing contact by email) — call `find_contact_by_email()` (shipped in mailgun-inbound track).
  - No `In-Reply-To` matches an existing conversation → **new conversation**.
  - Conversation's owner defaults to the org's inbox-triage assignee (from Track 1's endpoint config; new column `default_assignee_user_id UUID NULL` on `tbl_email_endpoint_details`).
- **Auto-create-contact toggle.** New column `auto_create_contact BOOLEAN DEFAULT true` on `tbl_email_endpoint_details`. When `true` and sender email doesn't match a contact: create a minimal contact (email + name from RFC `From: Name <email>`). When `false`: persist message with `contact_id = NULL` + `system_review_required = true`. Owner default is `true` (industry baseline per HubSpot / Front).
- **Forwarding wizard: Angular component.** Three-step wizard:
  - **Step 1 — Pick your provider.** Cards: Gmail, Google Workspace, Outlook.com, Outlook 365, Zoho Mail, custom.
  - **Step 2 — Copy your forwarding address.** Big display of `f-<token>@in.karmcrm.com` with copy button; **Show DNS?** disclosure (there is none — forwarding is just a rule at their provider).
  - **Step 3 — Follow the guide.** Provider-specific inline guide (screenshots + verbatim menu paths from each provider's help docs). At the end: **Send a test email** button → we watch for inbound on this token within 5 minutes → success/failure state renders in wizard.
- **Test-inbound watcher.** New endpoint `GET /api/v1/endpoints/{endpoint_id}/test-inbound-status`. Polls (or SSE) the `last_inbound_at` column on the endpoint's detail row; returns `waiting` / `received` with timestamp. Frontend polls every 5s during wizard Step 3; times out at 5 min with a "Didn't work? Recheck your provider settings" prompt.
- **New sidebar surface: Settings → Email → Inbound addresses.** Lists all `forwarded_address` endpoints per org. Shows: label, forwarding address, default assignee, auto-create toggle, last-inbound-at, activate/deactivate, delete.

## What this track does NOT do

- **No custom inbound subdomain per org** (`support.acme.com` → CRM). That's a follow-up custom-inbound-domain track. This track uses the shared `in.karmcrm.com` with per-endpoint tokens.
- **No IMAP pull as alternative to forwarding.** Users must forward; we don't offer "connect your Gmail inbox and we'll pull". Gmail OAuth already covers that via native sync.
- **No email-alias-as-user-identity.** Endpoint is org-level, assigned to a user for triage — but incoming mail's `To:` isn't a user login identity.
- **No mailing-list detection heuristics beyond the shipped Auto-Submitted / Precedence check** — a list-sub notification just becomes an inbound conversation with `auto_generated=true` (workflow-events skipped, but still visible).
- **No AI auto-triage / auto-categorization** — belongs in a separate assistant track.
- **No SMS/WhatsApp forwarding** — email only.
- **No forwarding-verification loop** (i.e. Gmail's "confirm this forwarding" email). We display the confirmation-catcher in wizard Step 3's test — the verification email lands in the endpoint's inbox where the user sees it and clicks the link at Gmail's end.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Endpoint type discriminator | **`forwarded_address`** on `tbl_channel_endpoints.endpoint_type` | Distinct from `smtp_reply_capture`. |
| Token shape | **`f-<12chars>`** base64url; column `forwarding_token` on `tbl_email_endpoint_details` (Track 1) | Prativani two-token model; matches shipped reply-token entropy. |
| Token uniqueness | **UNIQUE constraint** already on Track 1's column | Reuse. |
| Prefix disambiguation | **Local-part prefix (`in_` vs `f-`)** decides token-lookup path | One webhook URL, two code paths. |
| Mailgun Route | **One Route per env** matching `.*@in.karmcrm.com` — existing route from mailgun-inbound track is reused | No per-endpoint route explosion. |
| Contact matching | **`find_contact_by_email(org_id, email)`** — reused from mailgun-inbound | Same helper. |
| Auto-create-contact default | **`true`** — HubSpot / Front baseline | Owner can toggle per endpoint. |
| Default assignee | **Nullable `default_assignee_user_id` on details row** — falls back to org-inbox unassigned queue when NULL | Per-endpoint triage without hard-coding a user. |
| First-touch conversation | **New conversation created** — no attempt to thread across-conversations by sender-email | Threading is `Message-ID` / `In-Reply-To` chain only. |
| Wizard scope | **Three steps**: pick provider, copy address, follow guide + test-send | Matches HubSpot / Front minimal-wizard pattern. |
| Test-inbound watcher | **Endpoint polls `last_inbound_at`; 5s frontend cadence; 5-min timeout** | Simple, no SSE infra needed. |
| Provider guides | **Hard-coded strings in wizard component** — not fetched from CMS | 6 providers × ~5 steps each = 30 strings; ok in code. |
| Test-inbound signal | **`last_inbound_at` timestamp bump on any successful ingest** — no separate "test" flag | Any real inbound is a test-pass. |
| `default_assignee_user_id` NULL semantic | **"Org-inbox unassigned queue"** — visible to Owner+Admin | Matches existing conversations behavior. |
| Auto-create contact fields | **`email` (required), `first_name` + `last_name` parsed from RFC `From: Name <email>`** — nothing else | Minimal. Rich enrichment is a follow-up. |
| Auto-created contact source | **`source = "email_forwarded_address"`** in contact record | Reporting attribution. |

## Cases

**Concurrency & timing:**

1. Two admins simultaneously create `forwarded_address` endpoints. Each gets distinct `forwarding_token` (UNIQUE constraint + 10-try regenerate).
2. Wizard test-inbound and real customer inbound race at the same second. Both persist; test-inbound-watcher only cares about `last_inbound_at` bump.
3. Endpoint deactivated during in-flight webhook. Celery task's token-lookup returns inactive endpoint → audit `mailgun.inbound.endpoint_deactivated` + drop.
4. Auto-create-contact toggle flipped during in-flight ingest. Task reads the toggle at DAL-time; second concurrent send sees new value.

**Data lifecycle:**

5. Endpoint deleted — cascade: `ON DELETE SET NULL` on conversations' `endpoint_id` FK (conversations survive; endpoint attribution is nulled). Detail row cascades from endpoint delete.
6. Assignee user deleted. `ON DELETE SET NULL` on `default_assignee_user_id` — endpoint falls back to unassigned queue.
7. Contact merged. Existing merge cascade updates FKs on messages; endpoint's `last_inbound_at` unaffected.
8. Org soft-deleted. All endpoints hidden by `TenantScoped` policy.

**Ingest edge cases:**

9. Forwarded mail arrives with `From: bounced-notification@mailer-daemon`. Sender-auth checks apply; if SPF fails, `contact_id = NULL` + audit — matches shipped behavior.
10. Forwarded mail's original recipient (customer's own `support@acme.com`) is in `To:`, our address in `X-Forwarded-For`. Ingest uses Mailgun's `recipient` field (routing address = our token), not `To:` header, so this Just Works — same as Prativani's SES flow.
11. Multi-forwarded: customer forwards A → B → C → our address. Chain fine; ingest only sees the last hop. `Received:` headers preserved in payload for forensics.
12. Bounce landing at the forwarded address (customer's provider bounces the reply to our address). Auto-submitted detection catches it; persisted with `auto_generated=true`, no workflow events.
13. Attachment on forwarded mail identical to attachment on reply-capture. Same MIME allowlist + libmagic + two-phase staging applies — no new code path.

**Wizard flow:**

14. User closes wizard mid-step-3 before test-inbound arrives. Endpoint stays active with `last_inbound_at = NULL`; wizard can be re-launched anytime.
15. User's forwarding rule at Gmail asks them to click a verification link. Verification email hits our endpoint (Gmail sends it to the forwarding address it just set up) → wizard sees `last_inbound_at` bump → wizard shows "verification received; check Gmail". Verification-link click happens outside our UI.
16. Test-inbound arrives from an internal Gmail forwarding-loop-test (auto-generated). We still count it — any bump is proof forwarding works.

**Attacker lens:**

17. Attacker guesses `f-<token>` by brute force. 12-char base64url = 72 bits pre-slice; not brute-forceable over the internet.
18. Attacker knows a real token (stolen from screenshot / email log) and sends spoofed mail to it. SPF/DKIM fail path applies from mailgun-inbound; persisted with `spoof_suspected=true`, no workflow events.
19. Attacker floods our endpoint with signed Mailgun traffic. Per-sender hourly rate cap (Track 5) applies once shipped; until then, Mailgun's own throttling + disk-write throughput is the ceiling.
20. Attacker uses one org's token in the `To:` of a message addressed to a different org's `X-Forwarded-For`. Routing is on `recipient` (Mailgun's routing address), not `To:` header — attacker's `To:` header is inert.
21. Attacker forwards abusive content to our address to see if we surface it to the org. Yes, we do — that's the point. If it becomes a spam vector, Track 5's blocklist rules apply.

**Caller assertions:**

22. Wizard assumes `last_inbound_at` bump = forwarding works. Correct — a bump proves inbound path is complete.
23. Ingest task assumes local-part prefix disambiguation is exhaustive. Add `elif` fallback → `unknown_prefix` audit + drop.

## Tests (named-before-code)

**Endpoint + token:**

- `test_forwarded_address_endpoint_creation_generates_f_prefixed_token`
- `test_forwarding_token_length_12_chars_base64url`
- `test_forwarding_token_unique_across_all_endpoints`
- `test_endpoint_carries_default_assignee_and_auto_create_flags`

**Local-part prefix dispatch:**

- `test_ingest_in_underscore_prefix_routes_to_reply_capture_path`
- `test_ingest_f_dash_prefix_routes_to_forwarded_address_path`
- `test_ingest_unknown_prefix_audits_and_drops`

**Forwarded-address ingest:**

- `test_forwarded_ingest_uses_mailgun_recipient_not_to_header`
- `test_forwarded_ingest_creates_new_conversation_on_first_touch`
- `test_forwarded_ingest_threads_by_in_reply_to_when_present`
- `test_forwarded_ingest_falls_to_contact_latest_when_no_headers`
- `test_forwarded_ingest_auto_create_true_creates_contact_from_from_header`
- `test_forwarded_ingest_auto_create_false_nulls_contact_and_flags`
- `test_forwarded_ingest_assigns_conversation_to_default_assignee_when_set`
- `test_forwarded_ingest_assigns_to_unassigned_queue_when_default_null`
- `test_forwarded_ingest_spf_dkim_fail_persists_with_spoof_flag`
- `test_forwarded_ingest_auto_submitted_flags_auto_generated`

**Test-inbound watcher:**

- `test_last_inbound_at_bumps_on_first_ingest`
- `test_test_inbound_status_endpoint_returns_waiting_when_null`
- `test_test_inbound_status_endpoint_returns_received_after_bump`
- `test_test_inbound_status_scoped_by_org_id`

**Wizard (Karma):**

- `test_wizard_step1_renders_6_provider_cards`
- `test_wizard_step2_shows_forwarding_address_with_copy_button`
- `test_wizard_step3_polls_test_inbound_status_at_5s`
- `test_wizard_step3_timeouts_at_5min_shows_recheck_prompt`
- `test_wizard_step3_success_after_bump_shows_confirm_state`

**Inbound-addresses list (Karma):**

- `test_list_renders_all_forwarded_address_endpoints`
- `test_list_shows_last_inbound_at_relative_time`
- `test_list_deactivate_button_confirms_before_soft_delete`

**Cross-org isolation:**

- `test_forwarding_token_from_org_a_never_routes_to_org_b`
- `test_wizard_test_inbound_status_from_other_org_returns_404`

## Discovery reference

- **Prativani spec** (session-scoped, unsourced).
- **Mailgun Routes API** — MUST fetch: catch-all matcher syntax (`match_recipient(".*@in.karmcrm.com")`), does one route + payload-level local-part dispatch cost less than N routes with N tokens?, storage size cap for forwarded MIME.
- **Provider forwarding guides — MUST fetch verbatim** for wizard step 3:
  - Gmail personal (`Settings → Forwarding and POP/IMAP`)
  - Google Workspace (admin-level forwarding rules)
  - Outlook.com personal
  - Outlook 365 (via Exchange rules)
  - Zoho Mail
- **HubSpot Shared Inbox** — how the wizard flows for their forwarded-inbox connection. **Verbatim screenshots for wizard reference.**
- **Front** — same category; note: Front primarily uses IMAP-connect, not forwarding, so their wizard shape differs.
- **Missive** — forwarding-first flow.

Marked **unsourced** at plan time. Discovery is Step 1 of this track.

## Files touched

**Backend (new):**

- Alembic migration `0227_forwarded_address_endpoint.py` — adds `auto_create_contact`, `default_assignee_user_id` columns to `tbl_email_endpoint_details`; no new tables (endpoint model is Track 1's).

**Backend (edited):**

- `core/email/mailgun/service.py` — local-part prefix dispatch in Celery task.
- `core/email/mailgun/tasks.py` — new forwarded-address ingest branch.
- `core/conversations/adapters/email.py` — extend `_persist_inbound_email()` to accept `endpoint_type` and switch new-conversation-vs-thread behavior.
- `core/channel_endpoints/service.py` — new `create_forwarded_address_endpoint()`; test-inbound-status service.
- `core/channel_endpoints/router.py` — new POST/GET/DELETE endpoints for `forwarded_address` type; test-inbound-status endpoint.
- `core/contacts/service.py` — `auto_create_from_email()` helper (parse `From:` header → minimal contact).
- `core/channel_endpoints/schemas.py` — wizard schemas.

**Frontend (new):**

- `features/user/core/settings/email/inbound-addresses-tab.component.ts` (+ html + scss)
- `features/user/core/settings/email/forwarding-wizard.component.ts` — the 3-step wizard
- `features/user/core/settings/email/forwarding-wizard.service.ts`
- `features/user/core/settings/email/provider-guides.ts` — hard-coded provider-guide strings

**Config:** No new env vars.

## Step index

| # | Title | Status | Est files | Est effort |
|---|---|---|---|---|
| 1 | **Discovery**: Mailgun Routes matcher options; 6 provider forwarding guides fetched verbatim; HubSpot / Front / Missive wizard screenshots | Pending | 1 (discovery notes) | ~0.5 day |
| 2 | Backend: migration adds `auto_create_contact` + `default_assignee_user_id` cols; endpoint service `create_forwarded_address_endpoint()` | Pending | 3 | ~0.5 day |
| 3 | Backend: local-part prefix dispatch in Mailgun webhook + Celery task; forwarded-address ingest branch | Pending | 3 | ~0.75 day |
| 4 | Backend: contacts `auto_create_from_email()`; `_persist_inbound_email()` extended with `endpoint_type` behavior | Pending | 2 | ~0.5 day |
| 5 | Frontend: Inbound-addresses list tab + endpoint CRUD | Pending | 3 | ~0.5 day |
| 6 | Frontend: 3-step forwarding wizard + test-inbound watcher + provider guides | Pending | 4 | ~1 day |

**Total: 6 steps, ~3.75 days active dev + wait time on Gmail/Outlook verification-loop test.**

## Sequencing

- **Step 1 discovery first** — provider guides + Mailgun Routes model dictate wizard shape.
- **Steps 2 → 3 → 4** — schema + endpoint before ingest before contact auto-create (last because it's a soft dependency, not hard).
- **Steps 5 → 6** — list-tab before wizard (wizard is launched from list-tab).

## Reverse / rollback

- Every migration has working `downgrade`.
- Post-Step 3: revert Celery task's dispatch to `in_` prefix-only — forwarded-address inbound falls to `unknown_recipient` audit.
- Post-Step 6: hide wizard behind feature flag `EMAIL_FORWARDING_WIZARD_ENABLED`; existing endpoints keep receiving.

## Rules & conventions

- **10 non-negotiable rules:** every table `org_id` + RLS, `tbl_` prefix.
- **Router → Service → DAL** — pin-test.
- **Alembic revision ID ≤ 32 chars.**
- **Prettier on write** for Angular files.
- **Standard amber warning banner** for inactive-provider warning in wizard.
- **Provider guides fetched verbatim from provider docs** — no paraphrasing (would drift).

## Open items (deferred)

1. **Custom inbound subdomain** (`support.acme.com`) — follow-up track.
2. **Forwarding-loop detection heuristics** — Mailgun catches Return-Path loops; if a false-negative surfaces, add per-token loop-shed.
3. **Rich contact enrichment on auto-create** (phone from signature, company from domain) — assistant track.
4. **Custom (non-listed) provider guide** — v1 is 6 hard-coded; open field is a follow-up.
5. **SSE-based test-inbound watcher** instead of poll — v1 is 5s poll; upgrade if UX warrants.
6. **Bulk import** of existing customer-support-archive as CRM conversations — separate track.

## Depends on

- **Track 1 (endpoint abstraction)** — needs `endpoint_type` discriminator, `forwarding_token` col, `channel_endpoints` DAL.

## Blocks

- **Track 2 Step 5's platform-from Reply-To** uses this track's `r-token` model (already shipped via mailgun-inbound `inbound_token`, but this track's endpoint-scoped `reply_token` on Track 1's detail row supersedes). Coordinate at Step 5.
