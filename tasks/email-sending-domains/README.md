# Email Sending Domains — `tbl_organization_email_domains` + platform-from fallback + DNS records tab

Give every org a **claim your own sending domain** flow with Mailgun-verified DNS records displayed verbatim, a **platform-from fallback** (`org-<id>@mail.karmcrm.com`) when they haven't verified, and a **nightly re-verify state machine** that demotes drifted domains before they become deliverability incidents.

**Status:** Pending — plan drafted 2026-09-21. Depends on Track 1 (endpoint abstraction) landing first. Discovery required for Mailgun's exact `GET /v3/domains/{domain}` response shape + region split (US vs EU).

## Why this track exists

Today's `tbl_email_sender_domains` ([core/email_sender_setup/models.py](api/src/app/core/email_sender_setup/models.py)) is a **campaigns-only** artifact — it tracks SPF/DKIM/DMARC verification for one specific outbound path (bulk campaigns) with a placeholder DKIM public key (`"pending"`). It has:

- No Mailgun-blessed DNS records stored verbatim
- No re-verify cron — one-shot verify, then drift is invisible
- No state machine (`pending → verified → demoted → released`) — a domain that fails verification once looks identical to one that fails forever
- No MX records (inbound isn't in scope for that module)
- No fallback when unverified — either the org has a verified sender or the campaign send fails

The Prativani spec's `tbl_organization_email_domains` fixes all of this: **one table** that stores every DNS record verbatim as Mailgun returns them, runs nightly `GET /v3/domains/{domain}` re-verification, and exposes a state machine so operators see drift the day it happens rather than the day a customer complains about deliverability.

Alongside the domain table, this track also adds the **platform-from envelope** — when no verified own-domain exists, we send as `org-<uuid>@mail.karmcrm.com` with `Reply-To = r-<token>@in.karmcrm.com`. This unblocks trials, small orgs, and anyone who hasn't done DNS yet.

## What this track does

- **New table `tbl_organization_email_domains`.** Columns: `id UUID PK`, `org_id UUID FK`, `domain VARCHAR(253) UNIQUE`, `mailgun_domain_id VARCHAR(64)` (the ID Mailgun returns on create), `verification_status VARCHAR(16)` (`pending` | `verified` | `demoted` | `released`), `dns_records JSONB NOT NULL` (raw Mailgun response), `mx_verified BOOLEAN`, `spf_verified BOOLEAN`, `dkim_verified BOOLEAN`, `dmarc_verified BOOLEAN`, `last_verified_at DateTime`, `consecutive_failed_checks INT DEFAULT 0`, `demoted_at DateTime NULL`, `released_at DateTime NULL`, `region VARCHAR(4) DEFAULT 'us'` (`us` | `eu`), `created_at`, `updated_at`. `UNIQUE(domain)` — global unique because a domain can only be claimed by one org (Mailgun-side enforcement mirrored).
- **Mailgun API client wrapper: `core/email/mailgun/api_client.py`.** Wraps `POST /v3/domains` (create), `GET /v3/domains/{domain}` (verify + records), `DELETE /v3/domains/{domain}` (release), `PUT /v3/domains/{domain}/verify` (trigger re-check). Regional base URL from `MAILGUN_REGION` env var (`us` → `api.mailgun.net`, `eu` → `api.eu.mailgun.net`). Signed with `MAILGUN_API_KEY`; timeout 10s; retries on 502/503 only.
- **DNS records stored verbatim.** Whatever Mailgun's `GET /v3/domains/{domain}` returns in `sending_dns_records` and `receiving_dns_records` goes into the JSONB column as-is. **We do not hand-write these.** Frontend renders the JSONB — record-type + host + value + priority (for MX) + copy button. If Mailgun changes a record format tomorrow, our UI reflects it without a code change.
- **Verification state machine.** New domain claimed → `pending`. Nightly cron `sweep_email_domain_claims` calls `GET /v3/domains/{domain}`. All records pass → `verified`, `consecutive_failed_checks = 0`, `last_verified_at = now()`. Any record fails → `consecutive_failed_checks += 1`. Threshold `EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS` (default 3 consecutive) → `demoted`, owner emailed. Threshold `EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS` (default 14 days demoted) → `released`, DELETE from Mailgun, owner emailed. Newly-verified after demotion → `verified` again, `demoted_at = NULL`, owner emailed.
- **Platform-from envelope.** New env var `EMAIL_PLATFORM_SENDING_DOMAIN` (default `mail.karmcrm.com` — separate from `INBOUND_EMAIL_DOMAIN=reply.karmcrm.com`). New service function `resolve_send_envelope(org_id, from_hint=None) -> SendEnvelope` returns either the org's verified own-domain sender or the platform envelope with `From = org-<uuid>@mail.karmcrm.com`, `Reply-To = r-<token>@reply.karmcrm.com` (using Track 3's `r-token` — Track 3 has to ship before this Step 5 wires up, or Step 5 uses a placeholder that Track 3 fills). **Owner is notified in-app** the first time platform-from is used per org — this is a soft nag, not a block.
- **Sending cascade in `core/conversations/adapters/email.py`.** `send_email()` refactored to consult `resolve_send_envelope()` before choosing SMTP-sender / OAuth / platform. Priority: (1) caller-supplied `smtp_sender_id` or `oauth_account_id`, (2) org's default verified sender, (3) verified own-domain via platform Mailgun, (4) platform-from envelope. Falls through in order; if all miss, raise `SendNotConfiguredError`.
- **New router endpoints under `core/email_sender_setup/` (extend existing module — do not create new one).** `POST /api/v1/sender-domains` — claim domain (calls Mailgun create). `GET /api/v1/sender-domains` — list org's domains with status + records. `POST /api/v1/sender-domains/{id}/verify` — trigger immediate re-verify. `DELETE /api/v1/sender-domains/{id}` — release (calls Mailgun delete). All Owner-only.
- **Frontend: new "Sending domains" tab under Settings → Email.** Angular standalone component `sending-domains-tab.component`. Lists claimed domains with status badge (`Pending` / `Verified` / `Drift detected` / `Released`), a **Check now** button per domain, and an expandable "DNS records" section rendering each record verbatim from JSONB with per-value copy buttons. New-domain modal accepts the customer's domain string, POSTs to `/api/v1/sender-domains`, refreshes list. Standard amber warning banner (memory `feedback_standard_warning_banner_pattern.md`) when a domain drops to `demoted`.
- **Track 1 hookup.** `tbl_email_endpoint_details.domain_id` FK points at `tbl_organization_email_domains.id` for endpoints that carry a verified sending domain. Nullable — platform-from endpoints leave it NULL.

## What this track does NOT do

- **No DKIM keypair generation.** Mailgun mints the keys; we display them. Own-keypair signing is deferred.
- **No custom **inbound** domain** (`in.customer.com`). Track 3 or a later track handles receiving-side customization; this track is sending-only. The `tbl_organization_email_domains` schema supports it (region + MX fields), but the wiring stays in future work.
- **No per-user "send-as" identity.** Domain is org-level. Individual user aliases at `alice@acme.com` are a follow-up.
- **No warmup ladder** — Track 4 owns that. This track just picks the envelope; how fast we can push through it is Track 4's job.
- **No reputation dashboard** — Track 4.
- **No auto-DNS-provisioning** (Cloudflare/Route53 API to write records for the customer). We display; customer copies + pastes. Auto-provision is a follow-up.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Table name | **`tbl_organization_email_domains`** | Matches Prativani spec's canonical name; `tbl_` prefix per rule 2. |
| DNS records storage | **JSONB `dns_records`, populated verbatim from Mailgun `GET /v3/domains/{domain}`** | Provider is source of truth; format-drift resilience. |
| Region | **Per-domain `region VARCHAR(4)` column** (`us` / `eu`) | Prativani's data-residency finding — some tenants require EU. |
| Regional API base URL | **From `MAILGUN_REGION` env at boot, overrideable per-domain from row's `region` col** | Env is default; row wins. |
| Uniqueness | **Global `UNIQUE(domain)`** — one org can claim a given domain | Mailgun-side enforcement mirrors ours. Cross-org claim attempt → 409. |
| Verification cadence | **Nightly cron** for `pending` + `verified`; **hourly** for `demoted` (faster recovery) | Balance load + operator surface. |
| Demotion threshold | **`EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS = 3`** | One transient DNS blip shouldn't page anyone; three in a row is drift. |
| Release threshold | **`EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS = 14`** demoted | Two weeks of demote-nag → auto-release + free the Mailgun slot. |
| Platform-from local-part | **`org-<uuid>@mail.karmcrm.com`** — full UUID | No collision, no PII leak, no directory enumeration. |
| Platform-from Reply-To | **`r-<token>@reply.karmcrm.com`** using Track 3's `r-token` | Two-token model. Track 3 must ship before this Step 5. |
| Sending cascade order | **caller-supplied → org default → verified own-domain via Mailgun → platform-from → error** | Predictable + auditable. |
| Failure mode | **`SendNotConfiguredError`** raised at service layer; caller decides UI | No silent-fail. |
| Owner notification | **In-app notification + email** at every state transition (verified, demoted, released) | Operator visibility per Prativani spec. |
| DNS records shape | **Display Mailgun's exact strings** — no re-templating | UI is a dumb renderer over JSONB. |
| DNS render UI | **One `<app-tabs>` tab; per-record card with type/host/value/priority + copy button** | Matches existing embed-integrations settings pattern. |
| Own-domain-verify method | **Mailgun API `PUT /v3/domains/{domain}/verify`** — Mailgun does the DNS lookup | Our old `dkim_spf_check.py` module (which does direct DNS) is **not** used here; provider is source of truth. |
| Legacy `tbl_email_sender_domains` | **Kept in place, unused by new code** — campaigns module still references it | Removal is a follow-up track after campaigns re-points at the new table. |
| Backfill | **None** — this is an additive new table; existing campaign-domain rows do NOT migrate | Different semantic (campaigns' DKIM-selector vs Mailgun-managed keys). Campaigns keeps its old table until its own migration track. |
| Region-switch | **Not supported after claim** — releasing + re-claiming is the path | Mailgun doesn't support cross-region moves; mirroring their model. |

## Cases

**Concurrency & timing:**

1. Two orgs simultaneously claim `acme.com`. First INSERT wins (global UNIQUE), second gets 409 with `domain_already_claimed_by_another_org`.
2. Nightly cron and user-triggered `POST /verify` race on the same domain. Row-lock at service; second call waits + returns the fresh row.
3. Mailgun API 5xx during nightly re-verify. `consecutive_failed_checks` NOT incremented on 5xx (that's a provider blip, not a DNS drift). Retry next cycle.
4. Customer removes DKIM record right after verification. Next nightly re-verify fails; `consecutive_failed_checks = 1`. Doesn't demote until 3.
5. Platform-from first-use notification races with second send. Notification write is idempotent (`UNIQUE(org_id, notification_kind, notification_key)`).

**Data lifecycle:**

6. Org deleted. `ON DELETE CASCADE` cleans domain rows; separate Celery task calls Mailgun DELETE for each.
7. Domain released, then customer wants it back. Fresh claim (new row, new `mailgun_domain_id`) — Mailgun regenerates the DKIM keypair; customer re-publishes records.
8. Verified domain manually released by Owner. Immediate Mailgun DELETE + row set to `released`. Endpoints referencing `domain_id` cascade to NULL (Track 1's endpoint stays valid, just falls back to platform-from on next send).
9. Owner changes region from US to EU. Not allowed by service — must release + reclaim.

**Sending cascade:**

10. Org has no domain + no SMTP sender + no OAuth. `resolve_send_envelope()` returns platform-from. First send emits in-app notification "you're on platform sending".
11. Org has verified domain but Mailgun temp-unavailable during send. Cascade drops to platform-from as fallback for this send only. Next send retries verified path.
12. Campaign send explicitly requests SMTP sender by ID that belongs to another org. Service rejects with `sender_not_in_org` at cascade top.
13. Verified domain is in `demoted` state when a send happens. Cascade **skips** it → platform-from. Prevents deliverability damage during drift window.

**Attacker lens:**

14. Attacker claims `google.com`. Mailgun's own claim flow requires DNS proof of ownership before verification — attacker can't verify, sits in `pending` forever. Not a real threat.
15. Attacker POSTs `POST /sender-domains` with `mailgun_domain_id: "spoofed"`. Mass-assign protected — schema doesn't expose that field, service generates from Mailgun response.
16. Cross-org: Org B POSTs `/sender-domains/{Org-A-domain-id}/verify`. Service loads by ID scoped to caller's org_id → 404.
17. Attacker attempts SSRF via `POST /sender-domains` with `domain: "http://internal.svc/"`. Domain validator enforces RFC1035 label rules (no scheme, no path, TLD required); rejected.
18. Platform-from local-part guessing (`org-<uuid>@mail.karmcrm.com`) to enumerate orgs. UUIDs aren't guessable; no exposure.

**Caller assertions:**

19. Router assumes Mailgun response body has `sending_dns_records`. If missing/shape-changed, service raises `MailgunResponseInvalid` and doesn't write the row. Fail-closed.
20. Cron sweeper assumes `last_verified_at` monotonically advances. Enforced by service (never rewrites backward).

## Tests (named-before-code)

**Migration + schema:**

- `test_migration_creates_tbl_organization_email_domains`
- `test_migration_enforces_domain_unique_global`
- `test_migration_creates_region_column_default_us`
- `test_migration_down_removes_table`

**Mailgun API client:**

- `test_client_base_url_switches_on_MAILGUN_REGION_env`
- `test_client_base_url_switches_per_row_region_override`
- `test_client_retries_on_502_503_only`
- `test_client_timeout_10s_hard_cap`
- `test_client_signs_with_MAILGUN_API_KEY`

**Domain claim + verify:**

- `test_claim_domain_creates_pending_row_and_stores_dns_records_verbatim`
- `test_claim_domain_conflict_when_domain_already_claimed_by_other_org_returns_409`
- `test_claim_domain_validates_rfc1035_labels_rejects_scheme_urls`
- `test_verify_domain_all_pass_flips_to_verified_zeros_failed_counter`
- `test_verify_domain_any_fail_increments_failed_counter`
- `test_verify_domain_mailgun_5xx_does_not_increment_failed_counter`
- `test_nightly_cron_demotes_after_3_consecutive_failures`
- `test_hourly_cron_re_verifies_demoted_domains_only`
- `test_verified_after_demoted_notifies_owner_and_clears_demoted_at`
- `test_release_after_14_days_demoted_calls_mailgun_delete`

**Platform-from envelope:**

- `test_platform_from_local_part_uses_org_uuid_full`
- `test_platform_from_reply_to_uses_r_token_from_track_3_endpoint`
- `test_first_platform_from_send_emits_in_app_notification_idempotent`

**Sending cascade:**

- `test_cascade_prefers_caller_supplied_sender`
- `test_cascade_falls_to_verified_own_domain_when_default_absent`
- `test_cascade_skips_demoted_domain_uses_platform_from`
- `test_cascade_raises_send_not_configured_when_all_paths_miss`
- `test_cascade_sender_not_in_org_rejected_at_top`

**State machine:**

- `test_state_transitions_only_forward_pending_verified_demoted_released`
- `test_state_demoted_to_verified_emits_owner_notification`
- `test_state_released_removes_from_mailgun_side`

**Cross-org isolation:**

- `test_cross_org_verify_endpoint_returns_404`
- `test_cross_org_claim_conflict_reveals_no_info_about_owning_org`

**Frontend (Karma):**

- `test_domains_tab_renders_dns_records_from_jsonb_verbatim`
- `test_check_now_button_triggers_verify_and_refreshes_row`
- `test_demoted_domain_shows_amber_warning_banner`
- `test_copy_button_copies_record_value_exact`

## Discovery reference

- **Prativani spec** — user-provided architecture doc (session-scoped, unsourced). Frames the entity model + state machine.
- **Mailgun API docs** — MUST fetch in Step 1 discovery pass: `GET /v3/domains/{domain}` response shape (US + EU regions), `PUT /v3/domains/{domain}/verify` semantics, DNS record types returned (per prior conversation: TXT for DKIM, not CNAME — this differs from SES's format shown in the user's screenshot). Marked **PENDING** — do not proceed to Step 1 without fetching.
- **Existing `core/email_sender_setup/`** — reused for router placement + DKIM/SPF DNS-check helper (not called from new code but kept live for campaigns module until its own migration).
- **Existing frontend `sender-setup/`** — pattern for domain-setup modal reused; visual style already matches design refresh.
- **Interim competitor benchmarks (unsourced — `PRODUCT_BRIEF.md` does not exist):**
  - HubSpot Marketing Hub: connected email domain shows all TXT + CNAME records inline; "Verify" button; drift-detection banner. Weekly re-verify (not daily).
  - Mailchimp: domain claim requires 3 records; state = `Sending domain unverified` / `Ready to send` / `Requires action`. State transitions surfaced in Domains tab.
  - Klaviyo: dedicated sending domain vs shared; free tier is shared-only.

## Files touched

**Backend (new):**

- Alembic migration `0226_email_domains.py`
- `core/email/mailgun/api_client.py` — provider wrapper
- `core/email_sender_setup/models.py` — extend with `OrganizationEmailDomain` class (or split — decision at Step 1)
- `core/email_sender_setup/data_access.py` — new DAL functions
- `core/email_sender_setup/service.py` — claim, verify, release, resolve_send_envelope
- `core/email_sender_setup/router.py` — 4 new endpoints
- `core/email_sender_setup/schemas.py` — DNS record types, claim request/response
- `core/email_sender_setup/tasks.py` — Celery beat entries for nightly + hourly verify

**Backend (edited):**

- `core/conversations/adapters/email.py` — send-cascade in `send_email()`
- `main.py` — no new router registration (extends existing module)
- `shared/celery_config.py` — beat entries

**Frontend (new):**

- `features/user/core/settings/email/sending-domains-tab.component.ts` (+ html + scss)
- `features/user/core/settings/email/dns-record-card.component.ts` (shared, per-record renderer)
- `features/user/core/settings/email/claim-domain-modal.component.ts`
- `features/user/core/settings/email/sending-domains.service.ts`

**Config:**

- `config.env` — `EMAIL_PLATFORM_SENDING_DOMAIN=mail.karmcrm.com`, `MAILGUN_REGION=us`, `EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS=3`, `EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS=14`
- `secrets.enc.env` — `MAILGUN_API_KEY` (already present from mailgun-inbound track)

## Step index

| # | Title | Status | Est files | Est effort |
|---|---|---|---|---|
| 1 | **Discovery + Migration**: fetch Mailgun docs (regions + response shapes), create `tbl_organization_email_domains`, no code paths yet | **COMPLETED** (2026-09-21, DISCOVERY-NOTES.md from official PHP SDK; migration `0233` applied; downgrade + re-upgrade clean; `/v4/` corrected from `/v3/`; EU URL flagged unverified for later confirmation) | 4 (DISCOVERY-NOTES.md + migration + models.py extension + probe tests) | ~0.5 day |
| 2 | Backend: Mailgun API client wrapper (`api_client.py`) with region routing + retry policy | Pending | 3 | ~0.5 day |
| 3 | Backend: DAL + service `claim_domain()`, `verify_domain()`, `release_domain()`, `resolve_send_envelope()` | Pending | 4 | ~1 day |
| 4 | Backend: router endpoints (Owner-only 4 endpoints) + schemas + JWT scoping | Pending | 3 | ~0.5 day |
| 5 | Backend: sending cascade integration — refactor `send_email()` to call `resolve_send_envelope()` + `SendNotConfiguredError` | Pending | 2 | ~0.75 day |
| 6 | Backend: nightly + hourly Celery beat entries for domain verification + state-machine transitions + owner notifications | Pending | 3 | ~0.75 day |
| 7 | Frontend: Sending Domains tab + DNS records renderer + Claim modal + Check-now button + warning banner | Pending | 5 | ~1 day |

**Total: 7 steps, ~5 days active dev + Mailgun DNS wait time for smoke.**

## Sequencing

- **Step 1 discovery first** — Mailgun response shape locks the JSONB schema. Skipping means we'd need to migrate the JSONB shape once we ship.
- **Steps 2 → 3 → 4** — API client, then service, then router (bottom-up).
- **Step 5 depends on Track 3's r-token** for the platform-from Reply-To. If Track 3 hasn't shipped when we reach Step 5, use a placeholder token (fixed string) and fold in Track 3's token at that point.
- **Step 6 beat entries** independent — can ship before or after Step 7.
- **Step 7 last** — frontend consumes shipped API + doesn't block backend rollout.

## Reverse / rollback

- Every migration has working `downgrade`.
- Post-Step 5: revert `send_email()` to prior implementation; existing sender path still works.
- Post-Step 7: hide the Sending Domains tab behind a feature flag `EMAIL_DOMAINS_UI_ENABLED`. Backend APIs stay live for future re-enable.
- **Semantic irreversibility:** domains claimed with Mailgun during the feature's life stay claimed at Mailgun even after downgrade. Downgrade should release them via API before the DB drop.

## Rules & conventions

- **10 non-negotiable rules:** every new table has `org_id` + RLS, `tbl_` prefix, no `core/` → `packs/`.
- **Router → Service → DAL** — pin-test enforced.
- **Alembic revision ID ≤ 32 chars.**
- **Prettier on write** for Angular files (memory `feedback_prettier_on_write.md`).
- **Migrations run inline** (memory `feedback_execute_migrations_inline.md`).
- **Standard amber warning banner** (memory `feedback_standard_warning_banner_pattern.md`) for demoted state.
- **Shared components live in `shared/`** (memory `feedback_reusable_code_lives_in_shared.md`) — `dns-record-card` goes under `features/user/core/shared/dns/`.

## Open items (deferred)

1. **Own-DKIM-keypair rotation** — Mailgun manages keys today; own-key custody is a follow-up compliance ask.
2. **Auto-DNS-provisioning** via Cloudflare/Route53 API.
3. **Per-user send-as identity** — `alice@acme.com` vs org default.
4. **Custom inbound domain** (`in.customer.com`) — needs Track 3's forwarding-address flow to extend to per-org inbound domains.
5. **Sub-domain claims** (`marketing.acme.com`) — supported by Mailgun; not exposed in v1 UI.
6. **Warmup ladder** — Track 4.
7. **Sending reputation dashboard** — Track 4.
8. **Removal of legacy `tbl_email_sender_domains`** — after campaigns module migrates.

## Depends on

- **Track 1 (endpoint abstraction)** — Step 5 wires `tbl_email_endpoint_details.domain_id` FK.

## Blocks

- **Track 4 (reputation + warmup)** — two-tier limits (platform-from vs verified own-domain) require this cascade.
