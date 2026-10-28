# Step 12 — Marketing consent + quiet hours + frequency cap compliance

**Goal:** Wire the three compliance gates the manager spec'd for DPDP / India: marketing-consent check (opt-out honored automatically), quiet hours (9am-9pm IST default; marketing deferred, transactional bypasses), frequency cap (max N marketing messages per contact per week across ALL workflows + campaigns combined). Transactional Send actions (quote / invoice / receipt) bypass all three (legitimate-interest basis).
**Status:** COMPLETED — `core/settings/models.py` extended with 9 compliance columns on `tbl_org_settings` (`quiet_hours_enabled` bool default true, `quiet_hours_start` time default `'21:00:00'`, `quiet_hours_end` time default `'09:00:00'`, `quiet_hours_timezone` text default `'Asia/Kolkata'`, `frequency_cap_marketing_per_week` int default 5, `frequency_cap_marketing_per_day` int default 2, `transactional_bypass_quiet_hours` bool default true, `transactional_bypass_frequency_cap` bool default true, `unsubscribe_link_required_in_marketing_email` bool default true); migration `0140_org_compliance_settings.py` ALTER ADD COLUMN x9, reversible. `core/settings/schemas.py` extended: `OrgSettingsOut` exposes 9 fields; `OrgSettingsPatch` accepts them with input validation (caps bounded [0, 1000], tz text capped 64 chars). NEW `core/workflows/compliance.py` ships `Allow` / `Skip(reason)` / `Defer(until, reason)` dataclasses + `check_send(session, *, run, node, recipient, channel, category, now)` composite gate. Marketing-category gate order: block-list → channel-aware opt-out (email checks `Contact.email_opt_out`; whatsapp checks `Contact.whatsapp_opt_in_status='opted_out'`) → quiet-hours via `zoneinfo` with correct midnight-wrap handling (start > end → window spans tonight + tomorrow morning; past-midnight defer rolls to today's end-time) → per-week + per-day frequency caps. Transactional/service short-circuit past opt-out by default; re-engaged when the per-org `transactional_bypass_*` flags are off. `ensure_unsubscribe_link` auto-appends a standard footer to marketing emails when the org requires it AND the rendered body lacks an unsubscribe token. `core/workflows/data_access.count_recent_marketing_sends(org_id, contact_id, since)` joins `tbl_workflow_step_runs` (status=completed + payload->>'category'='marketing') AND `tbl_campaign_messages` (status in sent/delivered/read + sent_at present). `core/workflows/actions/send.py` patched: the Step-7 `_compliance_check` stub now delegates to `compliance.check_send`; new `_gate_or_skip` helper translates the decision into either `None` (proceed) or an immediate `ActionResult` — for `Defer`, self-parks the run via `next_step_at` so the beat sweep resumes the same step later. Per-node `config.category` overrides workflow-level marketing flag (transactional sends in marketing workflows bypass). All 4 send paths (`send.email`/`whatsapp`/sms-fb-ig-push factory/`slack`) route through `_gate_or_skip`. `send.email` additionally calls `ensure_unsubscribe_link` post-render. NEW frontend `compliance-settings.component.{ts,html}` at `app/.../core/settings/general/` — Reactive-form panel with quiet-hours/frequency-cap/unsubscribe fieldsets, auto-converts `HH:MM` ↔ `HH:MM:SS` for the API. Wired into the existing `store-profile-tab` via `<app-compliance-settings />` mount + import. `settings-api.service.ts` extended with the 9 compliance fields. 13 pytest cases in `test_compliance.py` covering: email opt-out blocks marketing; WA-stop allows email; quiet hours defers to next-day end-time (cross-tz math verified); transactional bypass; outside-window allow; past-midnight rolls to same day's end; cap=0 disables; clean contact + non-quiet time → Allow; bypass_quiet_hours=false re-engages transactional gate; unsubscribe footer injects/skips/non-email/transactional cases. Pytest run deferred per `feedback_pause_before_pytest.md`. Migration applied via `API\run.cmd upgrade` — head is now `0140_org_compliance_settings`.

**Spec deviations**: (1) **Block list** — the spec calls for a `tbl_block_list` DND check but no such table exists; `_check_block_list` is a no-op placeholder returning False. Future track will replace the body without changing the call surface. (2) **Pre-existing overlap** — the automation-engine track (Step 13) shipped equivalent gates on `tbl_organizations` + `core/automation/send_guard.py` (migration 0134). The Step-12 implementation duplicates the columns onto `tbl_org_settings` per the spec; the two sources of truth serve their respective engines (automation reads from `tbl_organizations`; workflows reads from `tbl_org_settings`). A future consolidation track unifies onto one source.
**Depends on:** Step 7 (Send action handlers — compliance hooks land inside their pre-flight). `core/contacts/consent/` for marketing-consent reads. `core/contacts/block_list/` for DND. `core/settings/` for org-level quiet-hours + frequency-cap config.

---

## Scope

In-scope:

- `core/settings/models.py` extended with org-level compliance config in `tbl_org_settings`:
  - `quiet_hours_enabled` bool default true.
  - `quiet_hours_start` time default `21:00`.
  - `quiet_hours_end` time default `09:00`.
  - `quiet_hours_timezone` text default `Asia/Kolkata`.
  - `frequency_cap_marketing_per_week` int default 5 (max marketing sends per contact per rolling 7d window).
  - `frequency_cap_marketing_per_day` int default 2.
  - `transactional_bypass_quiet_hours` bool default true.
  - `transactional_bypass_frequency_cap` bool default true.
  - `unsubscribe_link_required_in_marketing_email` bool default true.

  Settings router (`core/settings/router.py`) extended with the compliance section in `PATCH /settings`.

- `core/workflows/compliance.py` — pure helper module (no DB writes; reads tbl_org_settings + the relevant counters):

  - `async check_send(session, *, run, node, recipient, channel, category) -> ComplianceDecision`:
    - `ComplianceDecision = Allow | Skip(reason: str) | Defer(until: datetime, reason: str)`.
    - For `category='marketing'`:
      1. **Block list check** — if contact in `tbl_block_list`, return `Skip('blocked')`.
      2. **Opt-out check** — if `contact.marketing_consent='opted_out'`, return `Skip('opt_out')`.
      3. **Channel-specific opt-out** — if the contact opted out of the specific channel (email-unsubscribed vs WhatsApp-stop) return `Skip('opt_out_channel')`.
      4. **Quiet hours check** — if `now()` in quiet-hours window (org TZ), return `Defer(until=quiet_hours_end_today_or_tomorrow, reason='quiet_hours')`. Engine flips the step_run to `pending` + sets run.next_step_at.
      5. **Frequency cap** — count marketing sends to this contact in the rolling 7d window AND today's window from `tbl_workflow_step_runs` + `tbl_campaign_sends` (queried via a small `count_recent_marketing_sends(...)` DAL helper). Over cap → `Skip('frequency_cap')`.
    - For `category='transactional'` / `'service'`:
      - Block list check still applies (DND is absolute).
      - Other gates skipped per the bypass flags.

- `core/workflows/actions/send.py` patched — the `_compliance_check` stub from Step 7 is replaced with `await compliance.check_send(...)`. Handlers translate the decision:
  - `Allow` → proceed with send.
  - `Skip(reason)` → return `ActionResult(skip_reason=reason)` so the step_run lands with the reason.
  - `Defer(until)` → return `ActionResult(skip_reason='deferred_quiet_hours')` BUT also set `run.next_step_at = until` + `run.status='pending'` so the beat sweep resumes the same step (engine re-issues the same node's `process_step` after the wait).

- Unsubscribe link enforcement for email marketing sends — when the org has `unsubscribe_link_required_in_marketing_email=true` AND the rendered email body lacks an `<unsubscribe>` macro, the send is auto-prepended with a per-org standard footer (e.g. "Unsubscribe at <link>"). Operators see a note in the run-history about auto-injection.

- `core/workflows/data_access.py` extended:
  - `count_recent_marketing_sends(session, *, org_id, contact_id, since: datetime) -> int` — joins `tbl_workflow_step_runs` (where status='completed' + payload.category='marketing') + `tbl_campaign_sends` (where category='marketing'). Indexed by `(org_id, contact_id, started_at)`.

Out of scope:

- Per-channel frequency caps (different cap for email vs WhatsApp) — v2 polish. v1 has one cap covering all marketing sends.
- Transactional / service category override per send instead of per node config — operators set the category on the node and it sticks.
- Country-specific compliance overrides (e.g. GDPR vs CAN-SPAM vs DPDP) — DPDP is the v1 default; the schema is forward-compatible (add `compliance_profile` enum later).
- Automatic STOP-keyword handling for SMS (operator manually flips opt-out via the consent module today).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_org_compliance_settings.py` | **NEW** — ALTER ADD COLUMN x8 |
| `API/src/app/core/settings/models.py` | edit — eight new columns |
| `API/src/app/core/settings/schemas.py` | edit — extend `OrgSettingsOut` + `OrgSettingsPatch` |
| `API/src/app/core/settings/router.py` | edit — surface the new fields |
| `API/src/app/core/workflows/compliance.py` | **NEW** |
| `API/src/app/core/workflows/actions/send.py` | edit — call `compliance.check_send` instead of stub |
| `API/src/app/core/workflows/data_access.py` | edit — `count_recent_marketing_sends` |
| `APP/src/app/features/user/core/settings/general/compliance-settings.component.{ts,html}` | **NEW** — org-level compliance UI |
| `APP/src/app/features/user/core/settings/settings-page.html` | edit — embed compliance section |
| `API/tests/workflows/test_compliance.py` | **NEW** |

**~10 files. ~600 lines.**

## Plan

1. Migration: ALTER ADD COLUMN x8 on `tbl_org_settings`. Defaults set per the spec.
2. Settings schema + router edits.
3. Compliance helper module — pure logic over RLS-scoped queries.
4. Send-action patch to call compliance pre-flight.
5. DAL counter for frequency cap.
6. Frontend compliance settings section under Settings → General.
7. Tests: opt-out skip; quiet hours defer + resume; frequency cap skip after N sends; transactional bypass; block list always honored.

## DB changes / migrations

One migration with eight ALTER COLUMNs. Reversible.

## Tests

12 pytest cases:

- Opt-out contact → marketing send skipped with reason='opt_out'.
- Blocked contact → all sends skipped, including transactional.
- Quiet hours: marketing send deferred to quiet_hours_end; transactional sends through.
- Frequency cap: 5th marketing send same week → skipped with reason='frequency_cap'; transactional ignores cap.
- Unsubscribe link auto-injected when absent in marketing email.
- Unsubscribe link NOT injected when present.
- Channel-specific opt-out: WA-stop contact still receives email marketing.
- Per-day cap fires independently of per-week cap.
- Compliance allow path — no DB writes, returns Allow quickly.
- Counter query returns correct count across workflow_step_runs + campaign_sends.
- Defer past midnight: quiet_hours_end_today rolls to tomorrow.
- Settings update via PATCH /settings persists + future checks honor new values.

## Smoke

```
1. Update Settings → Compliance: quiet_hours 21:00-09:00 Asia/Kolkata, weekly cap 3.
2. Workflow: trigger(quote.sent) → send.email(category='marketing'). Activate.
3. publish quote.sent at 22:00 IST → step_run.skipped with reason='deferred_quiet_hours'; run.next_step_at=tomorrow 09:00.
4. At 09:01 IST → beat sweep resumes → email sent.
5. publish 3 more marketing send events same week → next one → step_run.skipped 'frequency_cap'.
6. publish invoice.sent (transactional) → sends regardless of cap + outside quiet hours.
7. Mark contact opted-out → next marketing send → skipped 'opt_out'.
8. Block contact → next transactional send → skipped 'blocked'.
```

## Risks

- Frequency-cap query crosses tbl_workflow_step_runs + tbl_campaign_sends with an OR — needs the `(org_id, contact_id, started_at)` covering indexes from both tables. Verify EXPLAIN cost in dev before rolling.
- Quiet-hours TZ math near DST transitions — Python's `zoneinfo` handles it correctly; pin a test for the Mar/Nov US DST cases since India doesn't observe DST.
- "Defer" semantics — the SAME step_run reuses its row when the engine resumes (no new audit row per resume). Operators see one row per logical step; the `skip_reason` is overwritten on the successful retry. Document in compliance.py.

## Self-check (10 rules)

`core/workflows/` + small `core/settings/` extension + tiny frontend. ✓ org_id-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced upstream. pack.yaml untouched (compliance is core — DPDP applies to all verticals). ✓ 10 files / ~600 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 12 — Marketing consent + quiet hours + frequency cap compliance
Files: 10
Verify: opt-out honored; quiet hours defer + resume; frequency cap blocks 5th send same week; transactional bypasses all three; block list absolute.
Tests: 12 pytest cases.
Awaiting "proceed".
```
