# Email Reputation + Warmup + Sending Limits — `tbl_organization_email_reputation`

Track sending reputation per-org (verified own-domain **and** platform-from separately), enforce daily ceilings that grow via a **warmup ladder climbed by sending** (not by calendar time), and shed sending when complaint/bounce rates cross thresholds. Wire the whole chain into the outbound send path: **ceiling → wallet debit → rate limit → dispatch**.

**Status:** COMPLETED (2026-09-21) — all 7 steps shipped end-to-end. Discovery locked at THRESHOLDS-LOCKED.md; migration `0235_email_reputation` applied inline; events webhook + evaluators + send gate + `v:` stamping + reputation dashboard all live.

## Why this track exists

Today: **zero reputation infrastructure.** No per-org warmup, no daily ceiling, no complaint/bounce tracking, no automatic shed when a tenant's abusive traffic starts damaging shared reputation. A single noisy tenant on the platform-from envelope (`org-<id>@mail.karmcrm.com`) can degrade deliverability for every other tenant on the same platform-from — because the platform-from domain IS shared.

Every mature email platform (Mailchimp, Klaviyo, HubSpot Marketing Hub, SendGrid) has this — it's not a nice-to-have. Warmup is a table-stakes feature: new sending sources start at low daily caps and climb as they demonstrate low complaint + bounce rates.

The Prativani spec's model:

- **Two-tier limits** — tight for platform-from (shared reputation carries platform risk), generous for verified-own-domain (their DNS carries their reputation).
- **Reputation thresholds** — complaint rate 0.05% (half of the "under review" ISP threshold), bounce rate 2.5% (half of 5%). Absolute event floor so one complaint on a 10-message day doesn't trip the tenant.
- **Warmup ladder** — daily ceiling by stage; climb by SENDING through `EMAIL_CAMPAIGN_WARMUP_EARN_FRACTION` of the current rung, not by calendar time. Any breach drops to floor stage.
- **Send-gate order** — ceiling → wallet debit → rate limit → dispatch. Out of allowance = `SKIPPED_SENDING_LIMIT`.

Prativani's numbers are **SES-shaped**. **We must confirm Mailgun's actual thresholds in Step 1 discovery** before locking anything.

## What this track does

- **New table `tbl_organization_email_reputation`.** Columns: `id UUID PK`, `org_id UUID FK`, `envelope_type VARCHAR(16)` (`platform_from` | `own_domain`), `domain_id UUID NULL FK tbl_organization_email_domains(id)` (NULL for platform_from), `warmup_stage INT NOT NULL DEFAULT 0`, `warmup_stage_earned_at DateTime NULL`, `warmup_stage_current_sent INT DEFAULT 0` (counter to compare against `EARN_FRACTION`), `daily_sent_count INT DEFAULT 0`, `daily_reset_at DateTime`, `bounce_count_24h INT DEFAULT 0`, `complaint_count_24h INT DEFAULT 0`, `delivered_count_24h INT DEFAULT 0`, `reputation_state VARCHAR(16) DEFAULT 'ok'` (`ok` | `warned` | `blocked_until_<ts>`), `blocked_until DateTime NULL`, `updated_at`. Unique `(org_id, envelope_type, domain_id)`.
- **Warmup ladder — 6 stages.** Configurable via env; defaults (subject to discovery review):
  - Stage 0: 50 messages/day
  - Stage 1: 200
  - Stage 2: 1,000
  - Stage 3: 5,000
  - Stage 4: 25,000
  - Stage 5: unlimited (well, still capped at plan tier — see Track 4 dependency on billing)
- **Climb-by-sending.** `EMAIL_CAMPAIGN_WARMUP_EARN_FRACTION = 0.5` (default) — must hit 50% of current stage cap **and** stay under thresholds to earn next rung. Advance triggered by a Celery beat every 4h that snapshots the 24h counters and evaluates promotion. No calendar-based time-in-stage — earn-through-behavior only, per Prativani spec.
- **Reputation shed cascade.** Thresholds (from env, defaults marked "SES-shaped, MUST verify vs Mailgun in discovery"):
  - Complaint rate threshold: `EMAIL_COMPLAINT_RATE_THRESHOLD = 0.0005` (0.05%). Half of ISPs' under-review floor.
  - Bounce rate threshold: `EMAIL_BOUNCE_RATE_THRESHOLD = 0.025` (2.5%). Half of ISPs' hard-fail floor.
  - Minimum event floor: `EMAIL_REPUTATION_MIN_EVENTS = 100`. Ratios don't apply below 100 events in the 24h window (one complaint on 10 messages doesn't shed).
  - **Both envelopes evaluated independently.** Verified own-domain drops to Stage 0 = own-domain-only shed. Platform-from breach = platform-from-only shed. Platform-from breach IS shared across tenants — see architectural findings below.
  - **Breach action:** `reputation_state = 'blocked_until_<ts>'`, `blocked_until = now() + EMAIL_BREACH_COOLDOWN_HOURS (default 4)`, `warmup_stage = 0`. Owner emailed. Send-gate rejects with `SKIPPED_REPUTATION_BLOCK`.
- **Mailgun events webhook.** `POST /api/v1/webhooks/mailgun/events` — signature-verified per shipped mailgun-inbound HMAC pattern. Handles `delivered`, `bounced` (permanent + temporary — distinguish), `complained` (spam-flag), `unsubscribed`, `rejected` (Mailgun-side pre-send rejection). Every event increments the appropriate 24h counter on `tbl_organization_email_reputation`. Idempotent via Mailgun's `id` field + Redis dedup cache.
- **Correlation via Mailgun custom variables (`v:` prefix).** Send call stamps `v:org` = org_uuid, `v:envelope` = `platform_from` | `own_domain`, `v:endpoint` = endpoint_id, `v:campaign` = campaign_id (or null). Events webhook reads these back to attribute to the right reputation row. **Naming discipline:** Mailgun's `v:` values are strings; UUIDs go as strings; enum values go as-is. Prativani's SES tag-value restriction `[A-Za-z0-9_-]` doesn't apply to Mailgun (Mailgun's `v:` values are looser) — but we stick to that character set anyway for portability.
- **Send-gate chain in `send_email()`.** Refactor from Track 2's `resolve_send_envelope()`:
  1. **Ceiling check.** `daily_sent_count` < warmup-stage cap? No → `SKIPPED_SENDING_LIMIT`.
  2. **Wallet debit.** Deduct 1 credit (or however billing is priced — Track 4 depends on billing surface; if credits aren't in place, this step is a no-op). Failed debit → `SKIPPED_WALLET_EMPTY`.
  3. **Rate limit.** Redis-backed per-envelope rate limiter (default 1000/hour own-domain, 100/hour platform-from — verify against Mailgun in discovery). Failed → `SKIPPED_RATE_LIMIT`.
  4. **Dispatch.** Mailgun send call.
  5. **Post-dispatch:** increment `daily_sent_count`, `warmup_stage_current_sent`, `delivered_count_24h` (delivered increments on delivery-event webhook, not send-time).
- **Daily reset cron.** `daily_reset_at` bumps at midnight UTC; counters zero.
- **24h rolling window reset cron.** Hourly beat that trims counter entries older than 24h. Implementation: counters are stored as time-bucketed keys in Redis (`rep:{org_id}:{envelope}:{bucket_hour}`) + summed on-read, so hourly beat just deletes >24h buckets. Simpler than a rolling INT column.
- **Reputation dashboard (frontend).** Settings → Email → Reputation. Shows per-envelope: current warmup stage (with progress bar to next), daily sent vs cap, 24h delivered/bounced/complained/rate-numbers, state badge (`OK` / `Warned` / `Blocked until <ts>`). One card per envelope (platform-from + each verified own-domain).
- **Owner notification triggers.** In-app + email at every: warmup-stage advance, state = `warned` (approaching threshold — one bucket over 80% of threshold), state = `blocked_until_*`.

## What this track does NOT do

- **No wallet / billing / credits system** — assumes Track 4 depends on shipped billing. If billing debit isn't in place, the wallet-debit gate is a no-op passthrough.
- **No SMS/WhatsApp reputation** — email-only.
- **No per-recipient suppression list** (bounced-address suppression) — Mailgun manages that at their side; we don't duplicate.
- **No reputation-driven send-time optimization** (send when reputation is highest) — future scheduling feature.
- **No IP-warmup** (we don't own IPs; Mailgun does).
- **No per-user-quota** — reputation is org-level.
- **No manual override** (Owner can't skip a warmup breach block) — v1 is automatic-only; support ticket = manual DB update.
- **No historical reputation graph** — v1 shows current state only. Charting is a follow-up.

## Locked decisions (with discovery gates flagged)

| Decision | Value | Why |
|---|---|---|
| Table name | **`tbl_organization_email_reputation`** | Prativani canonical. |
| Envelope discrimination | **Per-envelope row** (`platform_from` OR one per verified own-domain) | Independent shed cascades. |
| Warmup ladder | **6 stages, exponential-ish caps** — 50 / 200 / 1k / 5k / 25k / unlimited | Industry-standard shape; **must verify against Mailgun's own guidance in discovery**. |
| Climb rule | **50% of current-stage cap sent + under thresholds → advance** | Prativani "earn-through-behavior" model. |
| Advance cadence | **4h Celery beat** — snapshot + evaluate | Balance responsiveness + load. |
| Complaint threshold | **0.0005 (0.05%)** | **DISCOVERY GATE — SES numbers per Prativani; MUST fetch Mailgun's own guidance before locking.** |
| Bounce threshold | **0.025 (2.5%)** | **Same — SES-shaped, verify.** |
| Event floor | **100 events in 24h before ratios apply** | Small tenants don't trip on statistical noise. |
| Shed action | **`blocked_until = now() + 4h`, stage → 0, `reputation_state = 'blocked'`** | Cooldown + full warmup restart. |
| Correlation | **Mailgun `v:` custom variables** for `org`, `envelope`, `endpoint`, `campaign` | Provider-native mechanism. |
| Custom var charset | **`[A-Za-z0-9_-]` only** | Portability; matches Prativani's SES tag restriction defensively. |
| Send-gate order | **Ceiling → Wallet → Rate → Dispatch** | Cheapest-fail-first. |
| Rate limit backing | **Redis** — per-envelope + per-org key | Shared with existing rate-limit infra. |
| Rate limit values | **Own-domain 1000/hour, Platform-from 100/hour** | **DISCOVERY GATE — must match Mailgun's per-account limits.** |
| Wallet debit | **Optional — no-op if credits system not present** | Doesn't block Track 4 shipping on billing readiness. |
| Skip codes | **`SKIPPED_SENDING_LIMIT`, `SKIPPED_WALLET_EMPTY`, `SKIPPED_RATE_LIMIT`, `SKIPPED_REPUTATION_BLOCK`** | Distinct — attribution matters for support debugging. |
| Counter storage | **Redis time-bucketed keys, hourly buckets** | Rolling 24h without SQL row bloat. |
| Persistent state | **`tbl_organization_email_reputation` row is source of truth for `warmup_stage`, `reputation_state`, `blocked_until`** | Redis holds counters; DB holds state. |
| Owner notifications | **In-app + email** at stage-advance, `warned`, `blocked` | Standard notification pattern. |

## Cases

**Concurrency & timing:**

1. Two Celery workers fire delivery-event handlers for the same Mailgun event ID. Redis dedup catches second.
2. Send-gate and events-webhook race on the same counter. Redis atomic INCR — no lost updates.
3. Warmup advance evaluation runs while a send is mid-flight. Advance is a read-then-write; DB row-lock at service; second-worker sees advanced state on next tick.
4. Daily reset runs at 00:00:00 UTC while a burst of sends is in progress. Counter reset is atomic (`DEL rep:*` for expired buckets); sends after 00:00:01 start at fresh count.
5. Complaint arrives 5s after send. Send counted in `daily_sent_count`; complaint bumps `complaint_count_24h` at events webhook — attribution correct.
6. Mailgun replays an event we already processed. Redis `mgw:seen:events:<id>` catches (10-min TTL, same pattern as inbound).

**Reputation shed:**

7. Org sends 100 messages, 1 complaint (1%). Ratio > threshold BUT below event floor (min 100 — actually equals floor). Edge: floor is `>= 100` events → shed applies. Test locks this.
8. Org sends 500 messages, 3 complaints (0.6%). Way over threshold → shed platform-from envelope only. Own-domain envelope unaffected.
9. Org own-domain crosses bounce threshold. Own-domain-only shed; owner emailed; must wait 4h + regain warmup.
10. Platform-from breach — because platform-from is shared, another tenant's send RIGHT NOW sees no impact (their reputation row is separate). Platform reputation IS shared at Mailgun's side but our per-org rows shed independently. **This is the shared-quota constraint-sweep finding.**
11. Org in `blocked_until` state; owner clicks "release" in dashboard. No release button in v1 — auto-recovery only.
12. Blocked-until expires; next send-gate check → `reputation_state = 'ok'`, `warmup_stage = 0`, resume.
13. Recurring shed pattern (block, unblock, block within 24h) — no auto-permaban in v1; support alert triggered by Owner-notification volume.

**Warmup:**

14. Org at Stage 2 (1000 cap), sent 600 (60% → over 50% threshold), zero complaints. Next 4h beat advances to Stage 3.
15. Org at Stage 2, sent 400, no complaints. Next beat: still Stage 2. Sent 100 more (total 500 = 50%) → beat after advances.
16. Org at Stage 5, sends huge volume, small % complaints stay under threshold. Stays Stage 5.
17. Own-domain and platform-from advance independently — org can be Stage 4 own-domain, Stage 1 platform-from.
18. Verified own-domain revoked (Track 2 state → `demoted`). Own-domain reputation row soft-deleted or archived; next send falls to platform-from cascade + its own reputation row.

**Data lifecycle:**

19. Org deleted → cascade drops reputation rows + Redis counter keys (Redis cleanup via daily cron).
20. Verified own-domain deleted → cascade to `tbl_organization_email_reputation.domain_id` FK: `ON DELETE CASCADE` on the row (own-domain reputation gone).
21. Reputation row's `warmup_stage_earned_at` never resets on downgrade — retained for audit.

**Attacker lens:**

22. Attacker spins up a new org, sends huge volume of spam. Warmup ladder caps at Stage 0 = 50/day. Their reputation shed fires fast → they're auto-blocked. Reputation shed is per-org — they can't affect other tenants' reputation ROWS, but their sends did share Mailgun's platform-from domain reputation until we blocked. **Shared-quota risk**: mitigation is a low Stage 0 cap + fast shed.
23. Attacker sends `v:org=other_org_id` in send call to attribute their bounces to another org. Send-gate is called from OUR code — attacker doesn't control `v:` values, we do. Mass-assign protected.
24. Attacker forges Mailgun events webhook to zero their own bounce counter (send negative-value events). Mailgun's own webhook contract doesn't include arbitrary counter updates; only `delivered`/`bounced`/`complained` events. Signature-verified. Cannot craft a "zero counters" event.
25. Cross-org: Attacker in Org B queries reputation dashboard for Org A. Router scopes by JWT `org_id` → 404.

**Wallet/billing:**

26. Wallet debit fails at gate step 2. Message not sent; counter not incremented. Correct.
27. Wallet debit succeeds, dispatch fails (Mailgun 500). Message not sent; **refund the credit** (transactional — service re-adds the debited unit). Test asserts.
28. Wallet system doesn't exist yet. Gate step 2 is a no-op; other gates still apply.

**Caller assertions:**

29. Service assumes Mailgun events webhook always contains `event`, `id`, `recipient`, `v:*` fields. Missing field → audit + drop (don't crash, don't miscount).
30. Send-gate assumes `resolve_send_envelope()` returns a valid envelope. Cascade already asserts this — no re-validation.

## Tests (named-before-code)

**Migration + schema:**

- `test_migration_creates_tbl_organization_email_reputation`
- `test_migration_unique_constraint_org_envelope_domain`
- `test_migration_default_state_ok_warmup_stage_0`

**Warmup ladder:**

- `test_stage_0_daily_cap_50_by_default`
- `test_stage_advances_after_50_pct_sent_under_thresholds`
- `test_stage_does_not_advance_without_earn_fraction`
- `test_stage_does_not_advance_when_thresholds_breached`
- `test_platform_from_and_own_domain_advance_independently`
- `test_advance_cadence_4h_beat_evaluates_each_org_envelope`

**Reputation thresholds:**

- `test_complaint_rate_threshold_shed_over_0_0005`
- `test_bounce_rate_threshold_shed_over_0_025`
- `test_event_floor_100_not_shed_below`
- `test_event_floor_100_exact_boundary_sheds`
- `test_shed_blocks_until_now_plus_4h`
- `test_shed_resets_warmup_stage_to_0`
- `test_shed_owner_notification_fires_in_app_and_email`
- `test_blocked_until_expires_returns_state_to_ok`

**Events webhook:**

- `test_events_webhook_hmac_verify_fail_401`
- `test_events_webhook_delivered_bumps_delivered_counter`
- `test_events_webhook_bounced_permanent_bumps_bounce_counter`
- `test_events_webhook_bounced_temporary_does_not_bump_permanent_bucket`
- `test_events_webhook_complained_bumps_complaint_counter`
- `test_events_webhook_replay_id_rejected`
- `test_events_webhook_v_prefix_org_attributes_to_correct_row`
- `test_events_webhook_missing_v_prefix_org_audits_and_drops`

**Send-gate chain:**

- `test_gate_ceiling_rejects_over_daily_cap`
- `test_gate_wallet_debit_rejects_on_empty`
- `test_gate_wallet_refunds_on_dispatch_failure`
- `test_gate_rate_limit_rejects_over_hourly`
- `test_gate_reputation_blocked_rejects_until_expiry`
- `test_gate_order_ceiling_first_wallet_second_rate_third`
- `test_gate_dispatch_stamps_all_v_variables_on_mailgun_call`
- `test_gate_skipped_codes_distinct_per_reason`

**Counter storage:**

- `test_counters_time_bucketed_by_hour`
- `test_counters_hourly_beat_trims_buckets_older_than_24h`
- `test_counters_daily_reset_zeros_daily_sent`
- `test_counters_read_sums_last_24h_buckets`
- `test_counters_atomic_incr_on_concurrent_writes`

**Cross-org isolation:**

- `test_v_prefix_org_from_one_send_never_attributes_to_another_org`
- `test_reputation_dashboard_scoped_by_jwt_org_id`
- `test_own_domain_shed_does_not_affect_other_orgs_own_domains`

**Frontend (Karma):**

- `test_dashboard_renders_platform_from_card`
- `test_dashboard_renders_one_card_per_verified_own_domain`
- `test_dashboard_shows_warmup_progress_bar`
- `test_dashboard_blocked_until_shows_countdown`
- `test_dashboard_warned_state_shows_amber_banner`

## Discovery reference

**MANDATORY discovery items (Step 1 blocks all others):**

1. **Mailgun reputation model.** Is a Mailgun account's sending reputation account-scope, sub-domain scope, or per-domain? **This decides whether platform-from breaches affect other tenants at Mailgun's side or just at our shed-cascade side.** URL: Mailgun deliverability docs + support forum.
2. **Mailgun events webhook contract.** Full event-type list, retry semantics, signature verification identical to inbound?
3. **Mailgun `v:` custom variables.** Max count per send, max value length, allowed charset.
4. **Mailgun rate-limit tiers.** Per-account per-hour, per-domain per-hour, burst behavior.
5. **Mailgun-side suppression** (bounced-address list) — we don't duplicate but need to know it exists to avoid double-suppression.
6. **ISP thresholds** — actual public numbers from Gmail Postmaster, Microsoft SNDS, Yahoo Postmaster. Prativani's "0.05% / 2.5%" MUST be verified against these.

**Interim competitor benchmarks (unsourced):**

- **Mailchimp** — warmup happens at IP-shared-pool level; complaint threshold trips manual review.
- **Klaviyo** — dedicated-IP warmup wizard shows daily ramp targets; auto-throttle on complaint spike.
- **SendGrid** — automated IP warmup with hourly-cap ladder.
- **HubSpot Marketing Hub** — warmup implicit; explicit connected-domain reputation graph in dashboard.

Marked **unsourced** at plan time. Discovery is Step 1 of this track and is non-negotiable — locking thresholds from memory is exactly the failure DISCOVERY_RULES.md rule zero exists to prevent.

## Files touched

**Backend (new):**

- Alembic migration `0228_email_reputation.py`
- `core/email/reputation/__init__.py`
- `core/email/reputation/models.py` — `OrganizationEmailReputation`
- `core/email/reputation/schemas.py`
- `core/email/reputation/data_access.py`
- `core/email/reputation/service.py` — warmup evaluate, shed evaluator, counter accessors
- `core/email/reputation/router.py` — dashboard endpoint, per-envelope status endpoint
- `core/email/reputation/tasks.py` — 4h warmup-advance beat, hourly counter-trim beat, daily reset beat
- `core/email/reputation/counters.py` — Redis time-bucket counter helpers
- `core/email/mailgun/events_webhook.py` — `POST /api/v1/webhooks/mailgun/events` endpoint

**Backend (edited):**

- `core/conversations/adapters/email.py` — `send_email()` gate-chain refactor + `v:` variable stamping
- `core/email/mailgun/api_client.py` (Track 2) — extend send call to accept `v:` variables dict
- `main.py` — register events-webhook router
- `shared/celery_config.py` — 3 new beat entries

**Frontend (new):**

- `features/user/core/settings/email/reputation-dashboard-tab.component.ts` (+ html + scss)
- `features/user/core/settings/email/envelope-reputation-card.component.ts` — per-envelope card
- `features/user/core/settings/email/reputation.service.ts`

**Config:**

- `config.env`:
  - `EMAIL_WARMUP_STAGE_CAPS=50,200,1000,5000,25000,` (empty final = unlimited)
  - `EMAIL_CAMPAIGN_WARMUP_EARN_FRACTION=0.5`
  - `EMAIL_COMPLAINT_RATE_THRESHOLD=0.0005`
  - `EMAIL_BOUNCE_RATE_THRESHOLD=0.025`
  - `EMAIL_REPUTATION_MIN_EVENTS=100`
  - `EMAIL_BREACH_COOLDOWN_HOURS=4`
  - `EMAIL_RATE_LIMIT_OWN_DOMAIN_PER_HOUR=1000`
  - `EMAIL_RATE_LIMIT_PLATFORM_FROM_PER_HOUR=100`
- `secrets.enc.env` — `MAILGUN_EVENTS_SIGNING_KEY` (may be same as inbound key — verify in discovery)

## Step index

| # | Title | Status | Est files | Est effort |
|---|---|---|---|---|
| 1 | **Discovery**: fetch Mailgun reputation + rate limits + events + `v:` docs; confirm ISP thresholds; document find-vs-Prativani deltas | Pending | 1 (discovery notes) | ~0.75 day |
| 2 | Backend: migration + reputation table + counters (Redis helpers) | COMPLETED | 3 | ~0.75 day |
| 3 | Backend: events webhook + attribution via `v:` + dedup + retry | COMPLETED | 3 | ~1 day |
| 4 | Backend: warmup evaluator (4h beat) + shed evaluator + owner notifications | COMPLETED | 3 | ~1 day |
| 5 | Backend: send-gate chain refactor in `send_email()` — ceiling/wallet/rate/dispatch + skip codes | COMPLETED | 2 | ~1 day |
| 6 | Backend: `v:` stamping in Mailgun API client + campaign integration | COMPLETED | 2 | ~0.5 day |
| 7 | Frontend: Reputation dashboard tab + per-envelope cards + amber banner + email notifications wiring | COMPLETED | 4 | ~1 day |

**Total: 7 steps, ~6 days active dev + Mailgun account-side validation time for real events.**

## Sequencing

- **Step 1 discovery non-negotiable.** Nothing else starts until Mailgun's actual numbers are fetched. If web access unavailable → STOP per DISCOVERY_RULES.md.
- **Steps 2 → 3 → 4** — schema + events before warmup evaluation (which reads events counters).
- **Steps 5 → 6** — send-gate before `v:` stamping (`v:` is meaningless without the gate in place).
- **Step 7 last** — consumes shipped events + gate.

## Reverse / rollback

- Every migration has working `downgrade`.
- Post-Step 5: revert `send_email()` to pre-gate implementation via `EMAIL_REPUTATION_GATES_ENABLED = false`.
- Post-Step 3: unregister events webhook; Mailgun retries; counters stop advancing.
- **Semantic irreversibility:** `blocked_until` state persists across downgrade — Owner sees the block until timestamp expires or manual DB fix.

## Rules & conventions

- **10 non-negotiable rules:** every table `org_id` + RLS + `tbl_` prefix.
- **Router → Service → DAL** — pin-test.
- **Alembic revision ID ≤ 32 chars.**
- **Migrations run inline** (memory).
- **Prettier on write** for Angular files.
- **DB efficiency:** counter reads sum 24 bucket keys → one Redis pipeline, one round-trip; no N+1 on send-gate.
- **New Celery tasks must be added to worker autodiscover list** (memory `feedback_celery_task_autodiscover_list.md`).

## Open items (deferred)

1. **Historical reputation graph** — v1 shows current state only.
2. **Reputation-driven send-time optimization** — future scheduling.
3. **Manual override** for support-driven unblock — v1 requires DB fix.
4. **Per-user quotas** — org-level only in v1.
5. **Reputation-derived seat pricing** — billing coupling.
6. **Multiple Mailgun accounts per environment** for reputation isolation between customer segments — mentioned in constraint sweep.
7. **Bounce classification refinement** — soft vs hard, provider-specific reason codes.
8. **Unsubscribe events → contact-level opt-out cascade** — likely a separate consent-tracking track.

## Depends on

- **Track 1 (endpoint abstraction)** — `endpoint_id` used in `v:` variables.
- **Track 2 (sending domains)** — `domain_id` FK; two-tier limits require verified own-domain concept.

## Blocks

- Nothing hard. Tracks 5 (quarantine) + 6 (audit) can ship parallel; they don't share tables.
