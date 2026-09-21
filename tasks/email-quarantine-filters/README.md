# Email Quarantine + Filter Rules + Per-Sender Rate Cap — `tbl_email_quarantine` + `tbl_email_filter_rules`

Extend the shipped mailgun-inbound gate chain with **message-level quarantine** (held-mail pending operator release/discard), a **filter-rules engine** (per-org blocklist / allowlist by address, contact-flag, and domain), and a **per-sender hourly rate cap** so a single noisy external sender can't flood one org's inbox.

**Status:** Pending — plan drafted 2026-09-21. Depends on Track 1 (endpoint abstraction). No discovery gate — email hygiene is a mature category, industry-baseline applies per memory `feedback_industry_standards_baseline.md`.

## Why this track exists

Today's inbound gate chain (shipped mailgun-inbound track) either **accepts** a message (goes to conversation) or **DLQs** it (system-failure catch-all). There's no middle: a suspicious message either lands in the org's live inbox — visible to every user under Needs Review — or it disappears into a DLQ nobody looks at.

The Prativani spec's model separates these clearly:

- **Quarantine** = message-level HOLD for suspicious inbound. Operator sees the summary + can Release (goes to inbox as normal) or Discard (audit + delete). Reason codes distinguish `size_exceeded`, `blocked_sender`, `rate_capped`, `spam_verdict`, `virus_verdict`.
- **DLQ** = system-failure catch-all (worker exhausted retries, unknown recipient, multi-recipient). No operator action possible — operational review only.
- **Filter rules** = per-org configuration of what's allowed / blocked at the address / contact-flag / domain level. Allow wins over block (matches Prativani spec + Gmail's own filter-precedence model).
- **Per-sender hourly rate cap** = Redis-backed per-sender-address rate limiter that shuts down one abusive external sender without affecting the rest of the org's inbox.

## What this track does

- **New table `tbl_email_quarantine`.** Columns: `id UUID PK`, `org_id UUID FK`, `endpoint_id UUID FK tbl_channel_endpoints(id) ON DELETE CASCADE`, `mailgun_delivery_id VARCHAR(64) UNIQUE`, `from_address VARCHAR(255)`, `from_display_name VARCHAR(255) NULL`, `to_recipient VARCHAR(255)`, `subject VARCHAR(1024) NULL`, `body_snippet TEXT NULL` (first 500 chars, sanitized), `attachment_summary JSONB` (filenames + sizes, no content), `reason_code VARCHAR(32)` (`size_exceeded` | `blocked_sender` | `rate_capped` | `spam_verdict` | `virus_verdict`), `reason_detail JSONB`, `payload_path VARCHAR(512)` (full MIME on disk under `./storage/quarantine/{id}/`), `status VARCHAR(16) DEFAULT 'held'` (`held` | `released` | `discarded` | `auto_purged`), `held_at DateTime`, `resolved_at DateTime NULL`, `resolved_by_user_id UUID NULL FK tbl_users(id)`.
- **New table `tbl_email_filter_rules`.** Columns: `id UUID PK`, `org_id UUID FK`, `endpoint_id UUID NULL FK tbl_channel_endpoints(id)` (NULL = org-wide rule), `rule_type VARCHAR(16)` (`allow` | `block`), `match_kind VARCHAR(16)` (`email_address` | `email_domain` | `contact_flag`), `match_value VARCHAR(255)`, `label VARCHAR(128) NULL`, `created_by_user_id UUID FK tbl_users(id)`, `created_at`, `updated_at`. **Precedence:** address > contact-flag > domain within same rule_type; allow always beats block; rule_type ties broken by "most specific match wins".
- **Extended gate chain in `core/email/mailgun/service.py`.** Insert two new gates into the existing chain BEFORE the current spam-verdict spot:
  1. **Blocked-sender rules.** Check `tbl_email_filter_rules` for org + endpoint. Allow-match → skip block gate (allow-wins). Block-match → quarantine with `reason_code = blocked_sender`.
  2. **Per-sender hourly rate cap.** Redis counter `mgw:sender:{org_id}:{from_address_lowered}` — 20 messages/hour default, configurable via `EMAIL_INBOUND_PER_SENDER_HOURLY_CAP`. Threshold hit → quarantine with `reason_code = rate_capped`. Exceeded further → drop silently (audit only, no more quarantine rows — the cap already told us the sender is noisy).
- **Extended existing gates.** The shipped 25MB size cap + auto-submitted gate + spam-verdict + virus-verdict move from "reject to DLQ" behavior to "quarantine with reason code". All existing gate-triggered rejects become quarantine-instead-of-drop. **DLQ retains its system-failure role** (worker exhausted, unknown recipient) — separated from message-level quarantine.
- **Quarantine review UI.** Settings → Email → Quarantine. List with columns: from, to, subject snippet, reason, held at, actions. Per-row: **Release** button → moves message to normal ingest path (subject + body + attachments become a real `tbl_messages` row via the shared `_persist_inbound_email` helper); **Discard** → audit + delete row + delete on-disk payload. **Bulk actions**: select-all + release-all-safe (only rows with `reason_code = rate_capped`; blocks release for spam/virus). **Filter chips** by reason_code.
- **Filter rules management UI.** Settings → Email → Blocklist. Table listing all rules with add/edit/delete. Add-rule modal: type (allow/block), match kind (address / domain / contact flag), value input with inline validation. Owner + Admin only. Applying-to endpoint dropdown (org-wide by default).
- **Auto-purge held quarantine.** Celery beat weekly. Rows with `status = 'held'` and `held_at > 30 days` → `status = 'auto_purged'`, payload disk cleanup, owner notification if any purged that week. Configurable via `EMAIL_QUARANTINE_AUTO_PURGE_DAYS`.
- **Release audit.** Every release writes a `mailgun.quarantine.released` audit event with `resolved_by_user_id` — needed for compliance / spam-review audits.

## What this track does NOT do

- **No AI-driven spam classification** — v1 uses Mailgun's own X-Mailgun-Sflag / verdict headers only (Track 6 wires those).
- **No user-visible "junk folder"** — quarantine is Owner+Admin-only. Regular users don't see held mail.
- **No auto-release rules** ("if from *@trusted.com always release") — the allow-list on `tbl_email_filter_rules` does this at gate time, not post-quarantine.
- **No per-message pin/unpin** or manual re-quarantine — one-way transitions only.
- **No quarantine retention policy dashboard** — v1 auto-purges at 30d; policy configuration is a follow-up.
- **No cross-org shared blocklist** — every org's list is independent. Cross-tenant abuse patterns handled at Mailgun's side.
- **No per-recipient rate cap** (rate is per-**sender**, not per-recipient — the shipped design targets a noisy external sender flooding an org, not defensive throttling of a specific inbox).

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Table names | **`tbl_email_quarantine`** + **`tbl_email_filter_rules`** | Prativani canonical. |
| Quarantine reason codes | **`size_exceeded`, `blocked_sender`, `rate_capped`, `spam_verdict`, `virus_verdict`** | Prativani list; distinguish causes for operator triage. |
| Payload storage | **Full MIME on disk under `./storage/quarantine/{id}/`** — not in DB | Same pattern as pending-inbound (mailgun-inbound track). |
| Held-mail default retention | **30 days**, then `auto_purged` state | Balances operator patience + disk. |
| Purge cadence | **Weekly Celery beat** | Not daily — quarantine volume is low. |
| Filter rule precedence | **Allow > Block; within same type: address > contact-flag > domain** | Gmail's model + Prativani spec. |
| Filter rule scope | **Org-wide by default, per-endpoint optional** | Endpoint-scoped rules unlock "block this sender for support inbox only". |
| Rate cap default | **20 msgs/hour per sender address** | Industry-baseline; configurable. |
| Rate cap backing | **Redis time-bucketed counter** | Same pattern as reputation counters (Track 4). |
| Rate-cap over-exceed | **Silent drop after first quarantine** — audit only | Once flagged as noisy, no need to keep flooding quarantine. |
| Release-to-inbox | **Goes through shared `_persist_inbound_email`** — same code path as normal ingest | No divergent quarantine-release path. |
| Release re-authenticates SPF/DKIM? | **NO — release trusts the operator's judgment** | If SPF failed at gate time, operator releasing means they've decided the sender is legit despite. |
| Release-to-inbox conversation attribution | **New conversation OR existing thread by RFC In-Reply-To** — same threading rules | Consistent. |
| Spam-verdict quarantine | **Yes — moved from "reject" to quarantine** | Operator visibility on false positives. |
| Virus-verdict quarantine | **Yes — quarantined but flagged `blocked_release`** — operator cannot release, only discard | Prativani virus-verdict-wins policy; operator can't accidentally release malware. |
| Filter-rule storage of contact flags | **`match_value` = flag name; contact lookup at gate time** | Contact flags are a shipped feature; leverage existing. |
| Filter-rule mass edit | **v1 = individual CRUD; bulk-import CSV is a follow-up** | Keep v1 lean. |
| DLQ vs quarantine boundary | **DLQ = system failure (worker exhausted, unknown recipient, multi-recipient); Quarantine = message-level suspicion** | Different operator surfaces. |
| Bulk release safety | **Release-all only for `rate_capped` reason code**; `spam_verdict` + `virus_verdict` require per-row confirmation | Prevents accidental mass-spam release. |

## Cases

**Concurrency & timing:**

1. Same quarantined message released by two admins concurrently. Row-lock on `tbl_email_quarantine.status`; second admin gets 409 with current state.
2. Filter rule added mid-flight while an inbound message is in Celery. Rule read is at gate-time (post-signature-verify, pre-persist) — the message might slip through if the rule was added between gate-check and rule-read; acceptable, rules apply forward.
3. Rate cap resets at hourly bucket boundary while a burst is in flight. New bucket → new counter → sender resumes. Correct.
4. Bulk-release UI selects rows then user hits release while another admin edits rules. Independent — release doesn't consult rules.

**Data lifecycle:**

5. Quarantine row auto-purged. Disk payload deleted; row remains as `auto_purged` for audit trail.
6. Org deleted → cascade drops quarantine rows + disk payload cleanup task queued.
7. Endpoint deleted → CASCADE on `endpoint_id` FK deletes quarantine rows for that endpoint + disk payload cleanup.
8. Filter rule deleted → doesn't affect already-quarantined rows (they were quarantined when the rule was live; the audit trail shows why).
9. User who resolved a quarantine row is deleted. `ON DELETE SET NULL` on `resolved_by_user_id` — row keeps `resolved_at` but loses attribution.

**Release flow:**

10. Released message threads to existing conversation via RFC `In-Reply-To`. Goes through normal `_persist_inbound_email` — same behavior as if never quarantined.
11. Released message from `spam_verdict` reason — persisted; workflow events fire normally (operator's release IS the human trust signal).
12. Released message from `virus_verdict` reason — **blocked** at service layer; UI shows discard-only.
13. Released message with attachments that failed the MIME allowlist. Release re-applies the allowlist? **NO — attachments were stripped at gate time before quarantine**; release attaches nothing. Documented in UI.
14. Rate-capped-then-released message from a noisy sender. Doesn't reset the sender's rate counter. Future messages from same sender within same bucket still capped.

**Filter rules:**

15. Block `spam@evil.com`; message arrives. Blocked. Same sender same hour more messages → all quarantined (all block-reason, count separately from rate-cap).
16. Allow `trusted@partner.com`; but their message has SPF fail. Allow-list at filter-rules gate skips block-gate but NOT the SPF-based `spoof_suspected` handling — spoof-suspect still applies. **The allow-list overrides operator-set blocks, not sender-auth policy.** Test asserts.
17. Block `*@spammer.com` (domain rule); message from `notreally@spammer.com`. Domain match → quarantine.
18. Allow specific address + block whole domain: address-allow wins per precedence.
19. Contact-flag `do_not_engage` rule; sender email matches an existing contact with that flag → quarantine.
20. Contact has flag but there's no matching contact (unknown sender) → contact-flag rule doesn't apply; falls through to domain / block-list check.

**Rate cap:**

21. Sender at 20/hr cap in current bucket. 21st message → quarantine `rate_capped`. 22nd → silent drop. Bucket rolls → resumes.
22. Rate-cap sender across two org endpoints. Per-`(org, from_address)` bucket — the org's total from this sender caps, regardless of which endpoint.
23. Rate cap counter Redis outage. Fail-open (per shipped mailgun-inbound Redis fail policy on rate limiter). Rate cap doesn't apply during outage; noisy sender gets through. Acceptable given policy already locked.

**Attacker lens:**

24. Attacker POSTs `PATCH /quarantine/{id}` with `status: released` on another org's row. Router scopes by JWT org_id → 404.
25. Attacker crafts a message specifically to trigger `rate_capped` for a competitor sender they want to block. Rate cap is per-`(org, from_address)`; attacker can't attack another org's rate cap without being in that org.
26. Attacker uses `../` in filter rule `match_value` for path traversal. Value is stored + compared as string; no filesystem interaction — no exploit surface.
27. Attacker creates 10K filter rules to fill DB. Per-org rule count cap: `EMAIL_FILTER_RULES_MAX_PER_ORG = 500` (configurable). Over-cap POST → 409.
28. Cross-org: filter rule created in Org B affects Org A's inbound. Impossible — `tbl_email_filter_rules.org_id` scopes the read at gate time; Org A's gate never reads Org B rules.
29. Release button used to exfiltrate a quarantined `virus_verdict` sample. Service-layer block; UI-only "release" doesn't reach service.

**Caller assertions:**

30. Gate reads current filter rules on every message. Caching considered — 1s TTL per org via Redis to avoid DB hit per inbound. If a rule changes and cache TTL hasn't expired, next few messages might use stale rules. Documented acceptable.
31. Release assumes the on-disk payload exists. If missing (someone deleted the file manually), release fails with `payload_missing` error; row transitions to `discarded` with audit note.

## Tests (named-before-code)

**Migration + schema:**

- `test_migration_creates_tbl_email_quarantine`
- `test_migration_creates_tbl_email_filter_rules`
- `test_migration_cascade_from_endpoints`

**Gate chain:**

- `test_gate_blocklist_address_quarantines_message`
- `test_gate_blocklist_domain_quarantines_message`
- `test_gate_blocklist_contact_flag_quarantines_message`
- `test_gate_allowlist_beats_blocklist_at_same_kind`
- `test_gate_address_beats_contact_flag_beats_domain_within_type`
- `test_gate_per_sender_rate_cap_quarantines_at_threshold`
- `test_gate_per_sender_rate_cap_drops_silently_after_first_quarantine`
- `test_gate_size_exceeded_moved_from_reject_to_quarantine`
- `test_gate_spam_verdict_moved_from_reject_to_quarantine`
- `test_gate_virus_verdict_moved_to_quarantine_with_blocked_release`

**Quarantine lifecycle:**

- `test_quarantine_release_persists_via_shared_helper`
- `test_quarantine_release_threads_by_in_reply_to`
- `test_quarantine_release_from_virus_verdict_rejected_at_service`
- `test_quarantine_discard_deletes_row_and_disk_payload`
- `test_quarantine_bulk_release_only_allows_rate_capped_reason`
- `test_quarantine_auto_purge_after_30_days`
- `test_quarantine_auto_purge_notifies_owner_weekly_if_any`

**Filter rules:**

- `test_filter_rule_creation_validates_match_kind_and_value`
- `test_filter_rule_precedence_allow_over_block`
- `test_filter_rule_precedence_address_over_contact_flag_over_domain`
- `test_filter_rule_org_wide_and_endpoint_scoped_both_apply`
- `test_filter_rule_cap_per_org_enforced_at_500`
- `test_filter_rule_gate_read_cached_1s_per_org`

**Concurrency:**

- `test_two_admins_release_same_row_concurrently_second_gets_409`
- `test_rate_cap_bucket_boundary_resets_counter`

**Cross-org:**

- `test_release_on_another_org_row_returns_404`
- `test_filter_rule_from_other_org_never_gates_inbound`
- `test_rate_cap_per_org_from_address_key_isolated`

**Frontend (Karma):**

- `test_quarantine_list_renders_by_reason_code_chip`
- `test_release_button_confirms_on_spam_verdict`
- `test_release_button_hidden_on_virus_verdict`
- `test_bulk_release_toolbar_greyed_on_non_rate_capped_selection`
- `test_blocklist_add_rule_modal_validates_inline`
- `test_blocklist_rule_delete_confirms`

## Discovery reference

- **No mandatory discovery gate for this track.** Email hygiene (quarantine, allowlist/blocklist, per-sender rate cap) is industry-baseline per memory `feedback_industry_standards_baseline.md`.
- **Prativani spec** is the primary reference; `feedback_industry_standards_baseline.md` says bake these in without escalating.
- **Interim benchmarks (unsourced):**
  - HubSpot Shared Inbox: allowlist / blocklist + spam folder; no explicit quarantine-with-reason-codes.
  - Front: filters at inbox level; blocked-sender list; "spam" folder auto-purges at 30d.
  - Missive: filter rules + trash folder.
  - Gmail (as UX reference for filter precedence): allow-wins-over-block per label ordering.

## Files touched

**Backend (new):**

- Alembic migration `0229_email_quarantine_filters.py`
- `core/email/quarantine/__init__.py`
- `core/email/quarantine/models.py` — `EmailQuarantine`, `EmailFilterRule`
- `core/email/quarantine/schemas.py`
- `core/email/quarantine/data_access.py`
- `core/email/quarantine/service.py` — release, discard, bulk-release, filter CRUD
- `core/email/quarantine/router.py` — Owner+Admin endpoints
- `core/email/quarantine/tasks.py` — weekly auto-purge beat
- `core/email/quarantine/gates.py` — extended gate chain: blocklist + rate cap + verdict → quarantine handoff

**Backend (edited):**

- `core/email/mailgun/service.py` — reroute existing rejects (size, spam, virus) to quarantine
- `core/email/mailgun/tasks.py` — quarantine writer helper
- `main.py` — register quarantine router
- `shared/celery_config.py` — auto-purge beat

**Frontend (new):**

- `features/user/core/settings/email/quarantine-tab.component.ts` (+ html + scss)
- `features/user/core/settings/email/quarantine-row.component.ts`
- `features/user/core/settings/email/blocklist-tab.component.ts`
- `features/user/core/settings/email/filter-rule-modal.component.ts`
- `features/user/core/settings/email/quarantine.service.ts`

**Config:**

- `config.env`:
  - `EMAIL_INBOUND_PER_SENDER_HOURLY_CAP=20`
  - `EMAIL_QUARANTINE_AUTO_PURGE_DAYS=30`
  - `EMAIL_FILTER_RULES_MAX_PER_ORG=500`

## Step index

| # | Title | Status | Est files | Est effort |
|---|---|---|---|---|
| 1 | Migration: `tbl_email_quarantine` + `tbl_email_filter_rules` with cascade + probes | Pending | 2 | ~0.5 day |
| 2 | Backend: filter-rules DAL + service + router + validation + per-org cap | Pending | 4 | ~0.75 day |
| 3 | Backend: quarantine DAL + service (release, discard, bulk) + auto-purge beat | Pending | 4 | ~1 day |
| 4 | Backend: gate-chain extension — blocklist gate + rate cap gate + reroute size/spam/virus to quarantine | Pending | 2 | ~1 day |
| 5 | Frontend: Quarantine tab + Blocklist tab + modal + service | Pending | 5 | ~1 day |

**Total: 5 steps, ~4.25 days active dev.**

## Sequencing

- **Step 1** foundational.
- **Steps 2 → 3** — filter rules before quarantine (quarantine's blocklist reason depends on filter-rules DAL).
- **Step 4** wires the gate — depends on both service layers.
- **Step 5** consumes shipped API.

## Reverse / rollback

- Every migration has working `downgrade`.
- Post-Step 4: `EMAIL_QUARANTINE_GATES_ENABLED = false` → gate reverts to shipped mailgun-inbound reject behavior.
- Post-Step 5: hide tabs behind `EMAIL_QUARANTINE_UI_ENABLED = false`.

## Rules & conventions

- **10 non-negotiable rules.**
- **Router → Service → DAL.**
- **Alembic revision ID ≤ 32 chars.**
- **Prettier on write** for Angular files.
- **Standard amber warning banner** for `blocked_release` virus-verdict rows.
- **New Celery task added to autodiscover list** (memory).

## Open items (deferred)

1. **AI-driven spam classification** — v1 uses Mailgun verdicts only (Track 6).
2. **User-visible junk folder for regular users** — Owner+Admin only in v1.
3. **Bulk-import filter rules from CSV** — v1 is one-at-a-time.
4. **Cross-org shared blocklist / abuse-reports network** — deliberately out.
5. **Retention policy per reason code** — v1 uses one 30d default.
6. **Per-recipient rate cap** (defensive throttling of a specific inbox) — v1 is per-sender only.
7. **Filter rules on outbound** — v1 is inbound only.
8. **Auto-quarantine-release rules** ("release-on-arrival if from X") — the allow-list covers this at gate time.

## Depends on

- **Track 1 (endpoint abstraction)** — `endpoint_id` FK on quarantine + filter rules.

## Blocks

- **Track 6** — spam/virus verdict wiring depends on Track 5's quarantine landing spot.
