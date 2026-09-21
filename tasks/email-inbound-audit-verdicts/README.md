# Email Inbound Audit + Spam/Virus Verdicts — `tbl_email_inbound_deliveries` + verdict gates

Append-only **audit trail** of every webhook delivery attempt (before dedup, before ingest) for forensics + replay analysis, plus wire **spam + virus verdict gates** into the shipped mailgun-inbound chain — routing hits to Track 5's quarantine rather than dropping silently.

**Status:** Pending — plan drafted 2026-09-21. Depends on Track 5 (quarantine table). Small cleanup track — no discovery required.

## Why this track exists

Two small but load-bearing follow-ups the mailgun-inbound track deferred:

**1. No append-only audit trail of webhook receipts.** Today, the mailgun webhook writes payload to `./storage/pending-inbound/{uuid}/`, enqueues Celery, returns 200. If ingest succeeds, the pending-inbound dir is deleted. If it fails, DLQ. **There's no queryable record of "we received webhook X at time Y, with signature status Z, dedup status W."** That absence hurts three specific operations:

- **Replay-attack forensics** — if a replay hits the signature-fail path, the failed-sig audit event exists but the receipt itself doesn't (we dropped it). If we later want to see the pattern of attempted replays, there's nothing to query.
- **Ingest-flow debugging** — customer reports "I forwarded five test emails and only three landed" — we can't see the other two receipts to explain what happened.
- **Compliance / SLA claims** — Mailgun ingested and 200'd the webhook but the message never landed → we need a record separate from the delivery pipeline to prove receipt.

The Prativani spec's `tbl_email_inbound_deliveries` is exactly this: one row per webhook receipt, written **before** dedup so replays are visible.

**2. Spam + virus verdict gates.** Mailgun ships spam scoring in `X-Mailgun-Sflag` (spam flag) + `X-Mailgun-Sscore` and a virus verdict via headers/`X-Mailgun-Virus` field. Today, the shipped mailgun-inbound track doesn't gate on either — everything Mailgun accepts flows through our SPF/DKIM / auto-submitted / attachment gates. But Mailgun's ML-based spam and ClamAV-based virus scans catch things our gates don't (URL-shortener spam, EICAR-test virus, phishing-lookalike patterns). Routing verdict-hits to Track 5's quarantine rather than silent drop lets operators review false positives.

## What this track does

- **New table `tbl_email_inbound_deliveries`.** Append-only. Columns: `id UUID PK`, `mailgun_delivery_id VARCHAR(64) NULL`, `mailgun_message_id VARCHAR(255) NULL`, `received_at DateTime NOT NULL`, `signature_status VARCHAR(16)` (`valid` | `invalid` | `no_key`), `replay_status VARCHAR(16)` (`fresh` | `replayed`), `timestamp_status VARCHAR(16)` (`fresh` | `stale`), `recipient VARCHAR(255) NULL`, `sender VARCHAR(255) NULL`, `payload_size_bytes INT NULL`, `attachment_count INT NULL`, `outcome VARCHAR(24)` (`enqueued` | `signature_rejected` | `replay_rejected` | `timestamp_rejected` | `size_rejected_before_download`), `outcome_detail JSONB`, `client_ip INET NULL`, `user_agent VARCHAR(255) NULL`. **No `org_id` column** — this table is system-level (many outcomes happen before org resolution). Owner+platform-admin-only viewing.
- **Write point:** in `core/email/mailgun/service.py` — one INSERT immediately after signature check (whichever branch it took) and before pending-inbound disk write. Persist-then-process for the audit: audit row exists before any downstream processing, so if downstream crashes, the audit row is still there.
- **Retention.** 90 days by default (`EMAIL_INBOUND_DELIVERIES_RETAIN_DAYS = 90`). Daily Celery beat trims older rows. Rows never expose personal-message content — only `sender` / `recipient` / `size` / `outcome`.
- **Spam verdict gate.** In the extended gate chain (Track 5), check Mailgun's `X-Mailgun-Sflag` header + optional `EMAIL_SPAM_SCORE_THRESHOLD` (default 5.0 out of 10 — verify against Mailgun docs). Verdict = spam → quarantine with `reason_code = spam_verdict`, `reason_detail = {score, flag}`.
- **Virus verdict gate.** Mailgun's ClamAV integration surfaces via `X-Mailgun-Virus` header (present + non-empty = virus). Verdict = virus → quarantine with `reason_code = virus_verdict`, `blocked_release = true` (from Track 5).
- **Verdict gate ordering.** Runs after auto-submitted / blocklist / rate-cap but before SPF/DKIM enforcement. Rationale: verdict-hits are a stronger signal than sender-auth (Mailgun's scoring incorporates sender-auth too — separate check is redundant). If both spam + virus fire, virus wins (higher severity).
- **Frontend: system-admin audit view.** Only for platform admins (not per-org Owner). Simple list at `/admin/email-inbound-deliveries` (under legacy `features/admin/` — the untouched admin panel per CLAUDE.md). Actually — since `features/admin/` is off-limits per CLAUDE.md, add a scoped route at `features/user/core/settings/email/audit-log-tab.component` visible only to users with `platform.admin` permission. Table with pagination + date-range + outcome filter. No row-detail modal in v1 — the payload isn't stored, only metadata.

## What this track does NOT do

- **No message content in audit rows.** Only metadata. Content is at pending-inbound disk (if enqueued), quarantine disk (if held), or `tbl_messages` (if ingested).
- **No per-org filter on audit rows** — many outcomes happen before org resolution. Platform admins only.
- **No historical replay analytics** — v1 is a raw log. Aggregation dashboards are a follow-up.
- **No auto-alerting on replay-pattern detection** — v1 is passive log; alerting is a follow-up.
- **No verdict-appeal flow** — verdict-hit quarantined messages release via Track 5's normal release button.
- **No custom spam threshold per-org** — v1 is one platform-wide threshold.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Table name | **`tbl_email_inbound_deliveries`** | Prativani canonical. |
| Org scoping | **None (system-level table)** — no `org_id` column, no RLS | Many outcomes happen before org resolution. |
| Retention | **90 days**, daily beat purge | Balance forensics window + row-count growth. |
| Write point | **After sig check, before disk write** — one INSERT per webhook | Audit row exists even if disk write / Celery enqueue fails. |
| PII in audit rows | **`sender` + `recipient` only** — no subject, no body | Content lives elsewhere per pipeline stage. |
| Verdict-gate order | **After blocklist + rate cap, before SPF/DKIM** — verdict subsumes SPF/DKIM in most cases | Cheaper checks first + strongest signal wins. |
| Spam threshold | **`EMAIL_SPAM_SCORE_THRESHOLD = 5.0`** | Mailgun default; **verify in implementation with Mailgun docs**. |
| Virus verdict trump | **Virus wins over spam** — quarantined with `virus_verdict`, `blocked_release = true` | Higher severity. |
| Frontend location | **Under `features/user/core/settings/email/`** — NOT under `features/admin/` | Per CLAUDE.md, `features/admin/` is untouched. |
| Permission gate | **`platform.admin` permission required** | Per-org Owner doesn't get to see other orgs' receipts. |
| No row-detail modal | **List-only in v1** | No payload to display. |
| Table indexes | **`(received_at DESC)`, `(mailgun_delivery_id) WHERE mailgun_delivery_id IS NOT NULL`** | Time-order queries + dedup lookups. |
| Insertion cost | **Best-effort — audit failures do NOT block delivery** | Audit is telemetry, not gating. |

## Cases

**Concurrency & timing:**

1. Same webhook fires twice (Mailgun retry after our slow 200). Both rows write; unique constraint NOT enforced (audit trail is intentionally allowed-to-duplicate — captures the retry). Downstream dedup unchanged.
2. Audit INSERT fails (DB down). Warning logged, webhook continues. Audit is telemetry.
3. Retention beat and heavy new-INSERT rate on same partition. Non-blocking DELETE with `LIMIT 10000` per beat.

**Data lifecycle:**

4. Row aged past retention → deleted. No cascade to anything.
5. Quarantine row exists whose corresponding audit row is aged out. Independent — quarantine has its own metadata; audit row loss doesn't affect quarantine ops.
6. Platform admin's org deleted. Audit rows survive — they're system-level.

**Verdict gates:**

7. Spam score 4.9 (threshold 5.0). Below → not quarantined; ingest continues.
8. Spam score 5.0 (edge). Threshold check is `>=` → quarantined. Test locks boundary.
9. Virus header present but spam flag also. Virus wins; `reason_code = virus_verdict`.
10. Virus header empty string. Not treated as virus. Test locks.
11. Verdict-quarantined message released (spam) — normal release path per Track 5.
12. Verdict-quarantined message released (virus) — blocked at Track 5 service layer.

**Audit vs. pipeline:**

13. Webhook signature-fail → audit row `outcome=signature_rejected`, response 401. Downstream pipeline never touched.
14. Replay-cache hit → audit row `outcome=replay_rejected`, 401.
15. Timestamp too old → audit row `outcome=timestamp_rejected`, 401.
16. All gates pass → audit row `outcome=enqueued`. Downstream may still fail (worker exhausted) — audit outcome doesn't update. That's DLQ's job.
17. Payload > 25MB rejected pre-download → audit row `outcome=size_rejected_before_download`.

**Attacker lens:**

18. Attacker floods sig-fail traffic. Every attempt writes an audit row. Table grows — retention beat trims after 90d. No unbounded growth.
19. Attacker infers via response timing whether an audit-INSERT succeeded. Audit write is `asyncio.create_task()`-ed — response time constant.
20. Cross-org: Org B admin tries to view audit log. Permission check `platform.admin` fails → 403.

**Caller assertions:**

21. Frontend assumes `outcome` values are the fixed enum. Backend validates + returns 400 on unknown filter value.

## Tests (named-before-code)

**Migration + schema:**

- `test_migration_creates_tbl_email_inbound_deliveries`
- `test_migration_creates_received_at_desc_index`
- `test_migration_no_org_id_column`

**Audit writes:**

- `test_audit_row_written_on_signature_valid`
- `test_audit_row_written_on_signature_invalid`
- `test_audit_row_written_on_replay_rejected`
- `test_audit_row_written_on_timestamp_stale`
- `test_audit_row_written_on_size_rejected`
- `test_audit_write_best_effort_does_not_block_pipeline_on_failure`
- `test_audit_write_runs_before_pending_inbound_disk_write`
- `test_audit_write_response_time_constant_regardless_of_outcome`

**Retention:**

- `test_retention_beat_deletes_rows_older_than_90_days`
- `test_retention_batched_at_10k_per_beat`

**Verdict gates:**

- `test_spam_score_equal_threshold_quarantines`
- `test_spam_score_below_threshold_passes`
- `test_virus_header_present_quarantines_blocked_release`
- `test_virus_header_empty_not_quarantine`
- `test_virus_wins_over_spam_when_both_fire`
- `test_verdict_gate_order_after_blocklist_before_spf_dkim`
- `test_verdict_spam_release_path_works`
- `test_verdict_virus_release_path_blocked`

**Frontend (Karma):**

- `test_audit_list_requires_platform_admin_permission`
- `test_audit_list_paginates_by_date_desc`
- `test_audit_list_filters_by_outcome_enum`
- `test_audit_list_no_row_detail_modal_in_v1`

## Discovery reference

- **No discovery gate** — Prativani spec is authoritative; verdicts are simple boolean gates.
- **Mailgun docs to confirm at implementation time:** `X-Mailgun-Sflag` / `X-Mailgun-Sscore` header shapes, `X-Mailgun-Virus` semantics, default spam threshold. Non-blocking — worst case defaults mis-tuned, tunable via env.

## Files touched

**Backend (new):**

- Alembic migration `0230_email_inbound_audit_verdicts.py`
- `core/email/mailgun/audit_deliveries.py` — new DAL + write helper
- `core/email/mailgun/verdict_gates.py` — spam + virus gate logic

**Backend (edited):**

- `core/email/mailgun/service.py` — call audit write; call verdict gates in Track 5's chain
- `core/email/mailgun/router.py` — new admin GET `/admin/email-inbound-deliveries` endpoint
- `core/email/mailgun/tasks.py` — retention beat entry
- `shared/celery_config.py` — daily retention beat

**Frontend (new):**

- `features/user/core/settings/email/audit-log-tab.component.ts` (+ html + scss)
- `features/user/core/settings/email/audit-log.service.ts`

**Config:**

- `config.env`:
  - `EMAIL_INBOUND_DELIVERIES_RETAIN_DAYS=90`
  - `EMAIL_SPAM_SCORE_THRESHOLD=5.0`

## Step index

| # | Title | Status | Est files | Est effort |
|---|---|---|---|---|
| 1 | Migration: `tbl_email_inbound_deliveries` + retention beat + audit write in webhook + tests | Pending | 3 | ~0.75 day |
| 2 | Backend: spam + virus verdict gates in extended gate chain (Track 5's `gates.py`) + tests | Pending | 2 | ~0.5 day |
| 3 | Frontend: platform-admin audit log tab + service + permission gate | Pending | 3 | ~0.5 day |

**Total: 3 steps, ~1.75 days active dev.**

## Sequencing

- **Step 1 independent.** Ships first.
- **Step 2** depends on Track 5 (gate-chain extension point). Cannot ship before Track 5 Step 4.
- **Step 3** depends on Step 1's endpoint.

## Reverse / rollback

- Every migration has working `downgrade`.
- Post-Step 1: audit-write helper becomes no-op behind `EMAIL_INBOUND_AUDIT_ENABLED = false`.
- Post-Step 2: verdict gates disabled via `EMAIL_VERDICT_GATES_ENABLED = false` — falls back to Track 5's other gates only.

## Rules & conventions

- **Table is system-level (no `org_id`, no RLS)** — DEVIATION from 10 non-negotiable rules (which requires `org_id` on every table). This is a **deliberate exception** for audit-trail tables that cannot be org-scoped because their events happen before org resolution. **Documented deliberately** in this README. Precedent: `tbl_email_inbound_dlq` from mailgun-inbound also has `org_id NULL` for the unknown-recipient case.
- **Router → Service → DAL** — pin-test.
- **Alembic revision ID ≤ 32 chars.**
- **Prettier on write** for Angular files.
- **New Celery task added to autodiscover list** (memory).

## Open items (deferred)

1. **Aggregation dashboards** (replay-attempt rate, verdict-hit rate) — v1 is raw log.
2. **Auto-alerting** on replay pattern (many sig-fails from one IP within N minutes) — v1 passive.
3. **Per-org spam threshold customization** — v1 is platform-wide.
4. **Row-detail modal** with full metadata — v1 is list-only.
5. **Export audit log to CSV** — via existing export infrastructure, follow-up.
6. **Retention policy tiers** — 30d for successful, 365d for failed — v1 is one 90d.

## Depends on

- **Track 5 (quarantine)** — verdict gates route to quarantine table.

## Blocks

- Nothing.
