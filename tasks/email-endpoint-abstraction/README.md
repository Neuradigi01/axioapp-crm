# Email Endpoint Abstraction — `tbl_channel_endpoints` + `tbl_email_endpoint_details`

Refactor the shipped per-provider inbound-token storage into a single **endpoints** model so every inbound channel (Mailgun reply-capture, Mailgun forwarded address, Gmail OAuth mailbox, Microsoft OAuth mailbox, future custom-domain routes) is a row of one shared table with a type discriminator. **Pure structural move — zero new user-facing features.**

**Status:** Pending — plan drafted 2026-09-21. Part-C reviewers not yet run.

## Why this track exists

Today inbound routing is scattered across three tables that don't know about each other:

- `tbl_email_smtp_senders.inbound_token` — Mailgun reply-capture (mailgun-inbound track, shipped 2026-09-02)
- `tbl_email_accounts` — Gmail / Microsoft OAuth mailboxes (native sync)
- No table at all for the coming **forwarded-inbox** flow (Track 3) or **custom customer inbound domains** (future)

Every new inbound feature has to either bolt onto one of these tables (mailgun-inbound bolted `inbound_token` onto `tbl_email_smtp_senders`) or invent its own. That's how the existing schema grew and it doesn't scale — Track 3 would repeat the mistake by putting an `f_token` column somewhere arbitrary, Track 4 would need to correlate reputation across three unrelated tables, and Track 5's filter rules would have to be duplicated per endpoint type.

The Prativani spec's `tbl_channel_endpoints` + `tbl_email_endpoint_details` collapses this into one canonical table. Every downstream track (2/3/4/5/6) targets endpoints by ID, not by provider-specific column.

## What this track does

- **New table `tbl_channel_endpoints`** — one row per addressable inbound endpoint. Columns: `id UUID PK`, `org_id UUID FK`, `channel VARCHAR(32)` (`email` for now; future: `whatsapp`, `sms`), `endpoint_type VARCHAR(32)` (`smtp_reply_capture` | `forwarded_address` | `oauth_mailbox` | `custom_domain_inbound`), `label VARCHAR(128)`, `is_active BOOLEAN`, `created_at`, `updated_at`. Tenant-scoped via `TenantScoped` mixin.
- **New table `tbl_email_endpoint_details`** — email-specific fields per endpoint. Columns: `endpoint_id UUID PK FK`, `forwarding_token VARCHAR(32) UNIQUE NULL`, `reply_token VARCHAR(32) UNIQUE NULL`, `domain_id UUID NULL FK tbl_organization_email_domains(id)` (Track 2 populates this — nullable until then), `smtp_sender_id UUID NULL FK tbl_email_smtp_senders(id)`, `oauth_account_id UUID NULL FK tbl_email_accounts(id)`, `last_inbound_at DateTime NULL`. `forwarding_token` and `reply_token` are separate columns because the two-token model (Prativani spec) uses `f-<token>` for forwarding and `r-<token>` for reply-to — the same endpoint can carry both, or either.
- **Migration backfills every shipped SMTP sender.** For each row in `tbl_email_smtp_senders` where `inbound_token IS NOT NULL`: INSERT one row into `tbl_channel_endpoints` (type=`smtp_reply_capture`, org_id from sender, label=`from_address`) + one row into `tbl_email_endpoint_details` (endpoint_id from just-inserted row, `reply_token = inbound_token`, `smtp_sender_id` FK). Same for every row in `tbl_email_accounts` (Gmail + Microsoft), type=`oauth_mailbox`, `oauth_account_id` FK. **Existing `inbound_token` column stays** — the mailgun-inbound Reply-To injection at [core/conversations/adapters/email.py](api/src/app/core/conversations/adapters/email.py) still reads it. Column removal is a follow-up track (`email-legacy-token-removal`) after all downstream tracks migrate.
- **New DAL: `core/channel_endpoints/data_access.py`** — `find_by_forwarding_token(session, *, token)`, `find_by_reply_token(session, *, token)`, `find_active_for_org(session, *, org_id, endpoint_type)`, `create_smtp_reply_capture(session, *, org_id, smtp_sender_id, reply_token, label)`, etc.
- **New service: `core/channel_endpoints/service.py`** — endpoint lifecycle (activate/deactivate/soft-delete), token rotation, label edits. Transaction discipline per CLAUDE.md's layered convention.
- **New router: `core/channel_endpoints/router.py`** — Owner+Admin-only `GET /api/v1/channel-endpoints` for the future admin overview + activate/deactivate endpoints. Not user-facing yet.
- **Callers updated in-place — no behavior change.** The mailgun webhook's token→sender lookup ([core/email/mailgun/service.py](api/src/app/core/email/mailgun/service.py)) is refactored to call `find_by_reply_token()` on the new DAL, which returns `(endpoint, smtp_sender)`. If either the endpoint row or the sender row is missing/inactive, same audit event (`unknown_recipient`), same behavior. Golden byte-identical DB output test asserts this.

## What this track does NOT do

- **No new columns on `tbl_messages`.** Threading, dedup, RFC Message-ID scoping — all unchanged.
- **No new UI.** This is invisible to end users. The admin-overview endpoint exists but no frontend consumes it in this track.
- **No token rotation UI** — v1 is service-function only.
- **No feature additions** — no forwarded-address flow (Track 3), no reputation (Track 4), no quarantine gates (Track 5).
- **No removal of `tbl_email_smtp_senders.inbound_token` column.** Kept until every downstream track finishes; removal is a follow-up.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Table names | **`tbl_channel_endpoints`** + **`tbl_email_endpoint_details`** | `tbl_` prefix per CLAUDE.md rule 2; `channel_` prefix so future non-email channels (WhatsApp Business ID, SMS long-code) fit the same pattern. |
| Channel discriminator | **Column `channel VARCHAR(32)`** on parent table, `endpoint_type VARCHAR(32)` narrows within channel | Two-level discriminator so WhatsApp / SMS can grow their own `endpoint_type` enum without contaminating email's. |
| Detail-table shape | **Separate `tbl_email_endpoint_details` per-channel table** — NOT a JSONB `details` column on parent | Per-channel FKs (`smtp_sender_id`, `oauth_account_id`, `domain_id`) need real referential integrity; JSONB loses `ON DELETE CASCADE`. WhatsApp/SMS get their own `tbl_whatsapp_endpoint_details` etc. later. |
| Token column split | **`forwarding_token` + `reply_token` both on `tbl_email_endpoint_details`** — separate columns, both nullable, both `UNIQUE` | The two-token model needs them independent (one endpoint can carry one, the other, or both). Same endpoint row = same tenant + audit trail. |
| Legacy `inbound_token` | **Kept in place; new endpoint row `reply_token` mirrors it during backfill** | Zero-downtime cutover. Removal happens in a follow-up track after all callers migrate. |
| Backfill idempotency | **`WHERE NOT EXISTS` guard on both INSERTs** — retry-safe | Per memory `feedback_alembic_revision_id_length.md` + zero-downtime discipline. |
| Endpoint-lookup DAL | **`find_by_reply_token(token) -> (endpoint, details)` returns a tuple** — not lazy-loaded ORM relationship | Predictable performance; every caller wants both rows. |
| Migration revision ID | **≤ 32 chars** (e.g. `0225_channel_endpoints`) | Memory `feedback_alembic_revision_id_length.md`. |
| Router → Service → DAL layering | **Enforced by `test_layered_architecture_convention.py` pin-test** | New module lands clean from step 1. |
| Test approach | **Golden byte-identical DB output test** for mailgun webhook path before/after refactor | Refactor safety — if any observable state changes, catches it. |

## Cases

**Concurrency & timing:**

1. Two admins simultaneously deactivate the same endpoint. Row-lock at service; second gets 409 If-Match-ETag.
2. Mailgun webhook arrives during endpoint deactivation. If `endpoint.is_active = false` at Celery-task time, audit `mailgun.inbound.endpoint_deactivated` + drop (no partial ingest).
3. Backfill migration crash mid-run. Retry regenerates only WHERE NOT EXISTS — idempotent.
4. Two SMTP senders created concurrently. Each gets its own endpoint row (unique constraint on `reply_token`; regenerate on collision, 10 tries).

**Data lifecycle:**

5. SMTP sender deleted. `ON DELETE CASCADE` from `tbl_email_smtp_senders` → `tbl_email_endpoint_details.smtp_sender_id` → endpoint row is orphaned (details deleted, parent stays). Nightly sweeper deletes orphan endpoints (no details row for 24h + no recent activity).
6. OAuth account revoked at provider (Gmail refresh token expired). Endpoint stays `is_active=true` — reactivation is a Track 3 concern; Track 1 stays behavior-neutral.
7. Org soft-deleted. `TenantScoped` policy hides endpoint rows from all queries — same as every other tenant-scoped table.
8. Org hard-deleted. `ON DELETE CASCADE` from `tbl_organizations` cascades through both new tables.

**Cross-org isolation:**

9. Attacker POSTs a Mailgun webhook with a valid signature and captured `reply_token` from Org A while spoofing headers. Token resolves to Org A endpoint only — cross-org contamination impossible (endpoint carries `org_id` explicitly, DAL takes `org_id` in every threading call per mailgun-inbound Step 4 shared helper).
10. Two orgs somehow generate the same token (collision after 10 retries). `UNIQUE` constraint fails second insert — surfaces as `smtp_sender.token_collision_total` metric, operator paged. Not a security concern (constraint prevents write) but operational.

**Caller assertions:**

11. Router assumes `find_by_reply_token()` returns an org-scoped row. Verified in test: cross-org token from Org B lookup returns None.
12. Service assumes `endpoint.details` is non-null after INSERT. Verified: single-transaction INSERT of both rows; if second fails, first rolls back.

## Tests (named-before-code)

**Migration + backfill:**

- `test_migration_creates_tbl_channel_endpoints`
- `test_migration_creates_tbl_email_endpoint_details`
- `test_migration_backfills_smtp_senders_to_endpoints`
- `test_migration_backfills_oauth_accounts_to_endpoints`
- `test_migration_backfill_idempotent_on_retry`
- `test_migration_down_removes_new_tables`
- `test_migration_preserves_existing_inbound_token_column`

**DAL:**

- `test_find_by_reply_token_returns_endpoint_and_details`
- `test_find_by_reply_token_scoped_to_org_when_org_id_passed`
- `test_find_by_reply_token_returns_none_on_missing`
- `test_find_by_reply_token_returns_none_on_inactive_endpoint`
- `test_find_by_forwarding_token_returns_tuple`
- `test_create_smtp_reply_capture_regenerates_on_token_collision`

**Refactor safety (byte-identical):**

- `test_mailgun_webhook_ingest_byte_identical_before_after_refactor` — feed same payload to pre-refactor code and post-refactor code, assert DB state matches byte-for-byte.
- `test_oauth_receive_email_byte_identical_before_after_refactor`

**Cross-org isolation:**

- `test_cross_org_reply_token_lookup_returns_none`
- `test_endpoint_carries_org_id_explicitly_not_session_context`

**Lifecycle:**

- `test_smtp_sender_delete_cascades_to_endpoint_details`
- `test_endpoint_deactivation_causes_mailgun_ingest_audit_drop`
- `test_orphan_endpoint_sweeper_deletes_after_24h_no_details`

## Files touched

**Backend (new):**

- `core/channel_endpoints/__init__.py`
- `core/channel_endpoints/models.py` — `ChannelEndpoint`, `EmailEndpointDetails`
- `core/channel_endpoints/schemas.py`
- `core/channel_endpoints/router.py` — admin-only overview
- `core/channel_endpoints/service.py`
- `core/channel_endpoints/data_access.py`

**Backend (edited):**

- `core/email/mailgun/service.py` — replace direct `find_by_inbound_token()` on `email_senders.data_access` with `find_by_reply_token()` on `channel_endpoints.data_access`.
- `core/email/mailgun/tasks.py` — task carries `endpoint_id` in payload alongside legacy `smtp_sender_id`.
- `core/conversations/adapters/email.py` — `_persist_inbound_email()` accepts optional `endpoint_id`, stamps it into `payload.source_reference.endpoint_id` for audit.
- `main.py` — register `channel_endpoints.router` under `/api/v1`.

**Alembic:**

- One migration: `0225_channel_endpoints.py` — create both tables + backfill.

**Frontend:** None.

**Docs / runbook:** None (this is invisible to end users).

## Step index

| # | Title | Status | Est files | Est effort |
|---|---|---|---|---|
| 1 | Migration: create `tbl_channel_endpoints` + `tbl_email_endpoint_details` + backfill from SMTP senders + OAuth accounts | **COMPLETED** (2026-09-21, migration `0232` applied; 1 SMTP + 1 OAuth backfilled; downgrade + re-upgrade round-trip clean) | 4 (migration + models + `__init__` + probe test + main.py side-effect import) | ~0.5 day |
| 2 | Backend: `core/channel_endpoints/` module (models, schemas, DAL, service, router) | **COMPLETED** (2026-09-21, all 5 layered files + router registered + OpenAPI clean + DAL/service tests) | 7 (schemas + DAL + service + router + main.py + 2 test files) | ~0.75 day |
| 3 | Refactor: mailgun webhook uses `find_by_reply_token()` from new DAL; golden byte-identical DB test | **COMPLETED** (2026-09-21, `EMAIL_ENDPOINTS_REFACTOR_ENABLED` flag + `endpoint_id` stamped in payload + legacy fallback preserved) | 2 (tasks.py + byte-identical test) | ~0.5 day |
| 4 | Refactor: OAuth ingest (`receive_email`) records `endpoint_id` in message payload; golden byte-identical DB test | **COMPLETED** (2026-09-21, single edit to `email.py` covers Gmail + Microsoft; 300s TTL cache avoids N+1; graceful degrade on missing endpoint row) | 2 (email.py adapter + test file) | ~0.5 day |
| 5 | Nightly orphan-endpoint sweeper (Celery beat) + admin overview endpoint smoke | Pending | 3 | ~0.5 day |

**Total: 5 steps, ~2.75 days active dev.**

## Sequencing

- **Step 1 first, independent** — schema exists before any caller migrates.
- **Steps 2 → 3 → 4** in order — DAL exists before mailgun caller migrates; mailgun-caller migration verified before OAuth caller migrates.
- **Step 5 last** — sweeper + admin surface only makes sense once endpoints are populated end-to-end.

## Reverse / rollback

- Every step has working `downgrade`.
- Post-Step 3: `find_by_reply_token()` falls back to old `find_by_inbound_token()` behind a feature flag `EMAIL_ENDPOINTS_REFACTOR_ENABLED`. Flip off → old path restored.
- Post-Step 5: Full downgrade drops both new tables. Legacy `inbound_token` column on `tbl_email_smtp_senders` untouched → mailgun ingest keeps working.

## Rules & conventions

- **10 non-negotiable rules (CLAUDE.md):** every new table has `org_id`, `tbl_` prefix, RLS via `TenantScoped`, no `core/` → `packs/` imports.
- **Router → Service → DAL:** enforced by pin-test.
- **Alembic revision ID ≤ 32 chars** (memory `feedback_alembic_revision_id_length.md`).
- **Migration runs inline** via `API\run.cmd upgrade` before stop-and-report (memory `feedback_execute_migrations_inline.md`).
- **Test discipline:** golden byte-identical assertion is the ONLY safety net for a refactor of this size. No new behavior tests.

## Open items (deferred)

1. **Removal of `tbl_email_smtp_senders.inbound_token` column** — follow-up track after Tracks 2/3/4/5 all reference `tbl_email_endpoint_details.reply_token`.
2. **Custom customer inbound domains** (`in.customer.com`) — depends on this track + Track 2's `tbl_organization_email_domains`.
3. **WhatsApp / SMS endpoint types** — same shape, own detail table.
4. **Admin UI for endpoint management** — v1 is API-only.

## Depends on

Nothing. This is the foundation. Tracks 2/3/4/5/6 all sit on it.

## Blocks

- Track 2 (`email-sending-domains`) — needs `endpoint.domain_id` FK.
- Track 3 (`email-inbound-forwarding`) — needs `endpoint_type=forwarded_address` + `forwarding_token` column.
- Track 4 (`email-reputation-warmup`) — reputation is per-domain-per-endpoint, not per-sender.
- Track 5 (`email-quarantine-filters`) — filter rules attach to endpoint IDs.
