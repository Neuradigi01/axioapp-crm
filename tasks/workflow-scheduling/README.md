# Workflow Scheduling

Add a **Schedule** object to the Workflows module so operators can attach one or more time-based fires to any workflow — Once, Daily, Weekly, Monthly, Custom Interval, Specific Date/Time, or Cron (Advanced) — running its actions automatically without an inbound business event. Timezone-aware, DST-safe, quiet-hours-integrated, missed-run policy-aware, cross-tenant-safe by construction.

**Revised 2026-08-05** after the PLANNING_RULES Part C reviewer gate (Attacker + Architect + Absence). All P0/P1 findings folded in below; disagreements noted where they exist.

## Why this track exists

Manager directive 2026-08-05: allow scheduled execution of workflow actions (send templates, notify, trigger any action node) without manual intervention or inbound event. Use cases the manager named:

- Send a welcome message 10 minutes after a lead is created *(already covered by existing event trigger + wait node — not this track)*.
- Send a follow-up email every Monday at 10:00 AM.
- Send a payment reminder 3 days before invoice due date.
- Send birthday/anniversary greetings automatically.
- Fire a workflow every day at 9:00 AM to notify stale leads.
- Any recurring reminder, notification, or automation at a defined interval.

Rationale — the workflows engine already covers **event-triggered** flows; the missing dimension is **time-triggered** flows. The `time.daily_tick` event is declared in [event_catalog.py:126](API/src/app/core/events/event_catalog.py#L126) but no emitter exists, and it's coarse-grained (once a day, org-midnight only) — insufficient for the use cases above. Every mainstream CRM ships fine-grained scheduling (HubSpot "Scheduled workflows", Zoho Schedules, Salesforce Scheduled Flows, ActiveCampaign Date-based automations).

## What this track does

- **New object: `Schedule`, attached to any workflow.** A schedule is NOT a trigger-kind swap — it is an **independent, additive** firing mechanism. Any workflow (event-triggered, un-triggered, or seeded) can have zero, one, or many schedules attached. The workflow's existing event trigger (if any) continues to fire independently; schedules fire on top. Seeded workflows (e.g. "Birthday Wish" firing on `contact.birthday`) become schedulable — a user can attach "also run every Monday 9 AM" without editing or replacing the seeded event trigger.
- **New table `tbl_workflow_schedules`.** N:1 to workflows. Stores `workflow_id`, `org_id`, `contact_id` (nullable — see date-anchored future-proofing), `schedule_kind`, `config_json`, `timezone`, `starts_at`, `next_run_at` (UTC), `last_run_at` (UTC), `runs_completed`, `end_at`, `max_runs`, `active`, `name` (operator label), `on_missed`, `concurrency_policy`, `consecutive_empty_fires`, `created_by`, `updated_at` (ETag source). Partial index on `(next_run_at) WHERE active = true` for the sweep.
- **New audit columns on `tbl_workflow_runs`.** `trigger_kind` (`event | schedule | manual`), `trigger_source_id` (UUID, nullable — schedule_id for scheduled runs, event_id for event-triggered), `triggered_by_user_id` (nullable — set for manual runs). Backfill migration: existing rows get `trigger_kind='event'`. Enables end-to-end audit ("who caused this run") and closes the reviewer-flagged audit-shape ambiguity.
- **Sweep shares code path with `sweep_waits`.** Not a duplicated `sweep_schedules` task. The existing `workflows.tasks.sweep_waits` (60s beat) is extended to also pick due schedule rows via a second query in the same tick. One beat entry, one Celery worker discipline, one operational primitive. Both queries use `SELECT ... FOR UPDATE SKIP LOCKED`. Per-row savepoint so a poison row (malformed `config_json`, croniter raise) auto-deactivates that row + writes an audit event and the sweep continues — no batch rollback, no infinite crash loop.
- **Dual-dispatch: publish event AND direct engine call.** On fire, sweep publishes `workflow.schedule_fired` event (envelope: `{org_id, workflow_id, schedule_id, schedule_run_uuid}`) for observers (audit, reporting, future subscribers) AND calls `engine.start_run(workflow, contact_id=<from schedule row>, trigger_event_id=<server-generated uuid4>)` directly for the actual run. Trigger-handler idempotency key = the same `schedule_run_uuid`, protecting against event replay. UUID never returned to any client API.
- **Six user-facing recurrence presets** in the Builder, plus one advanced:
  1. **Run Once** — specific date + time.
  2. **Daily** — every day at HH:MM (per-schedule tz).
  3. **Weekly** — selected days-of-week at HH:MM.
  4. **Monthly** — day-of-month (clamp: 31 → last day of month) OR nth-weekday.
  5. **Custom Interval** — every N minutes / hours / days. **Minimum 5 minutes enforced.**
  6. **Advanced (cron expression)** — validated with `croniter`, computed inter-fire distance ≥ 5 min enforced (not just string-match `*/1`), "next 5 fires" preview.
- **Timezone-aware from day one.** Each schedule stores its own `timezone` (default = org.timezone with fallback to UTC if org.timezone is NULL). All `next_run_at` stored as UTC. Recurrence math done in local tz, converted to UTC. DST handled by `zoneinfo` + `croniter` defaults (spring-forward → skip missing hour; fall-back → run once). Timezone whitelisted against `zoneinfo.available_timezones()` at create/update.
- **Croniter safety net.** Recurrence expression re-validated on every sweep-load (not just at create — DB could be mutated by import/repair paths). Compute wrapped in 500ms hard timeout; a schedule whose recurrence math times out auto-deactivates with `deactivation_reason='recurrence_timeout'` + audit event.
- **Missed-run policy is a per-schedule enum.** `on_missed: skip | run_once | backfill_all` (default `skip`). Matches HubSpot's "enroll contacts inactive-window" toggle. When forward-compute skips ≥1 fire, sweep writes a `schedule.missed_fire` audit event with the miss count regardless of policy — no silent beat-outage.
- **Concurrency policy is a per-schedule enum.** `concurrency_policy: allow | forbid | replace` (default `forbid` — matches k8s CronJob default and prevents the classic time-triggered double-send trap). `forbid` skips fire if a previous run is still executing; `replace` cancels the in-flight run and starts a new one; `allow` matches event-triggered semantics.
- **Quiet-hours integration.** Reuses existing `workflows.compliance` quiet-hours check on the send-node side. Scheduled fire enrols regardless of quiet-hours; the send action defers to the next allowed window.
- **End conditions.** Any combination of: `end_at` (must be ≥ `starts_at`, rejected if < starts_at), `max_runs`, or manual pause (`active = false`). Row goes `active = false` when exhausted; a distinct "Ended (past)" state is surfaced when an admin edit deactivated the schedule (vs natural exhaustion), and the workflow owner is emailed on any admin-triggered deactivation to catch sabotage.
- **Fire-rate + capacity caps.** Per-org: `max_active_schedules = 500` (soft cap, configurable), `max_fires_per_hour_per_org = 1000` (evaluated by sweep before enrolment; skip + audit-log when exceeded). Per-schedule: consecutive `audience_empty` fires ≥ 20 auto-deactivate the row + notify owner (protects against runaway noise).
- **Cross-org write-path isolation.** Every schedule-CRUD endpoint calls `data_access.get_workflow_by_id_and_org(workflow_id, current_user.org_id)` FIRST and returns 404 (not 403) on mismatch — never trusts a body-supplied `workflow_id` or `org_id`. Mass-assignment blocked at schema layer: `ScheduleCreate` and `ScheduleUpdate` schemas expose only user-editable fields; `runs_completed`, `next_run_at`, `last_run_at`, `consecutive_empty_fires`, `active` (write-restricted to pause/resume-specific endpoints), `org_id`, `created_by` all server-owned and rejected if present in payload.
- **Optimistic lock on schedule PATCH.** `If-Match: <updated_at ISO>` header required on PATCH; 409 on mismatch. Reviewers all flagged this as cheap-and-worth-it; scheduling IS a high-contention surface when two admins fix the same "fires an hour early" bug.
- **Concurrent-editing conflict cases documented** — see Cases §26–29 for the specific two-user scenarios (pause+edit race, workflow-delete during config, ownership transfer mid-edit).
- **Contact-merge and contact-delete cascade.** Schedule row's `contact_id` FK (nullable): on merge → repoint to surviving contact (matches existing contact-merge FK cascade); on delete → deactivate schedule + audit event `schedule.deactivated_contact_deleted`. Prevents orphaned schedules pointing at deleted contacts.
- **Orphan-run reaper.** Sweep's second responsibility: find `pending` runs older than 1 hour with no active worker lock → mark `errored` with `error_reason='orphaned_pending'`. Protects against the sweep-crash-mid-commit case (Absence #3): if the sweep dies between `engine.start_run` commit and the schedule's `next_run_at` advance, the same schedule refires — reaper cleans the abandoned first run.
- **RLS-in-Celery honored.** Sweep sets `SET LOCAL app.current_org_id` per row before calling `engine.start_run` (matches request-context pattern). Query itself is a service-role scan (necessary for cross-org batch) but every dispatch enforces per-row tenancy. Explicit `org_id` join filter on the sweep query as belt-and-braces.
- **`croniter` added to `pyproject.toml`.** Pinned to a maintained major version. Explicit dependency, not implicit.

## What this track does NOT do

- **Multi-recipient scheduled sends.** "Every Monday 9 AM send this template to all leads matching X" is a **Campaigns feature**, not a workflow feature. Reason: `tbl_workflow_runs` has a single-valued `contact_id`; fanning out to N recipients from one run breaks per-run quiet-hours, per-contact idempotency, per-run failure semantics. Campaigns module already ships scheduled + audience + chunked + audited multi-recipient sends via `dispatch_scheduled_campaigns_task`. This track fires **single-recipient runs only**: schedule's `contact_id` = specific contact (nullable = "run without a contact dimension", e.g. an internal `create-task` or `notify-admin` workflow). Multi-recipient scheduling is a Campaigns-parity follow-up track, not this one.
- **Audience-filter resolver.** Removed from scope for the reason above. A user who wants "send to 500 contacts every Monday" uses Campaigns; a user who wants "remind contact X 3 days before invoice due" uses this track with `contact_id` set.
- **Recipient-local timezone sends.** "Send at 10 AM in *each recipient's* local tz" is a distinct feature and requires per-contact tz. Deferred.
- **Per-node retry policy.** Existing gap flagged in `workflows-absorb-automation` open items — scheduled sends inherit the same behaviour (no Celery retry on transient failure) as event-triggered sends. Shared follow-up.
- **Business-time / working-hours awareness.** "Only fire during working hours" beyond quiet-hours is not supported. Operators can approximate via cron `0 9-17 * * 1-5`.
- **Holiday calendars.** Not v1.
- **Cron per-second granularity.** Croniter minutes-only; 6-field (with year) or 6-field (with seconds) crons rejected at API with a clear error message.
- **`time.daily_tick` emitter.** Independent decision — this track does not need it (uses dual-dispatch on schedule rows). A future track can add a per-org midnight-tick publisher for cross-cutting subscribers without breaking this design.
- **Sub-minute precision.** Sweep runs every 60s, so precision is `±60s, never earlier than target`. Documented in Builder UI. If sub-minute becomes a real ask, revisit sweep cadence — not for v1.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Storage model | **Dedicated `tbl_workflow_schedules` table**, N:1 to workflows, nullable `contact_id` | Partial index on `next_run_at` makes sweep O(due rows). Multiple schedules per workflow. Nullable `contact_id` leaves the door open for date-anchored triggers (Open items §4) without a second table. |
| Schedule vs trigger | **Schedule is additive, not a trigger swap.** Event trigger + schedules fire independently. | Direct manager ask 2026-08-05: seeded workflows must be schedulable without losing their event trigger. Matches HubSpot's "multiple enrollment triggers" model. |
| Sweep task | **Extend `sweep_waits` to also pick schedule rows**, not a duplicated `sweep_schedules`. | Reviewer flag (Architect §1): reproducing partial-index/`SKIP LOCKED`/forward-compute is duplication. One beat entry, one lock discipline. |
| Trigger dispatch | **Dual-write: publish `workflow.schedule_fired` event + direct `engine.start_run` call.** | Reviewer flag (Architect §2): private-call bypass loses audit/reporting/future-subscriber observability. Event goes to bus; direct call does the actual run (event bus is one-to-many broadcast, not the fire mechanism). Idempotency key `schedule_run_uuid` shared between both. |
| Server-side dedup key | **Server-generated `uuid4()` at fire time**, never returned to any client API, stored with unique `(org_id, schedule_id, next_run_at)` in the runs table. | Reviewer flag (Attacker C3): forgeable/replayable if exposed. |
| Recurrence storage | **`schedule_kind` enum + `config_json` JSONB**. Enum = `once | daily | weekly | monthly | interval | cron`. | Kind determines how sweep computes `next_run_at`; config is kind-specific. |
| Minimum inter-fire | **5 minutes hard floor**, enforced at API create/update AND at sweep re-validation. Applies to `interval` and `cron` kinds. | Reviewer flag (Attacker C1): `*/1` cron not caught by `* * * * *` string-match. Compute distance, don't string-match. |
| Timezone source | **Per-schedule column, defaults to org.timezone, UTC if org.timezone NULL.** Whitelisted against `zoneinfo.available_timezones()` at create + sweep-load. | Multi-region ops; NULL-safety per reviewer (Absence §5). |
| DST behaviour | **`zoneinfo` + `croniter` defaults** — skip missing hour, run-once fall-back. | Matches Linux cron, HubSpot, Zoho. |
| Missed-run policy | **Per-schedule enum: `skip | run_once | backfill_all`, default `skip`.** Always writes `schedule.missed_fire` audit event with miss count when forward-compute skips ≥1 fire. | Reviewer flag (Architect §5, Attacker H3): skip-only silently loses payment reminders during outages. HubSpot exposes the choice. |
| Concurrency policy | **Per-schedule enum: `allow | forbid | replace`, default `forbid`.** | Reviewer flag (Architect §10): allow-parallel is the classic time-triggered double-send trap. `forbid` matches k8s CronJob default. |
| Enrolment `contact_id` | **From schedule row's `contact_id` column** (nullable). NULL enrolments already supported by engine per `trigger_handlers.py:222`. | Explicit per-schedule target rather than "always NULL". |
| Null-contact action safety | **Every action handler audited in Step 2** for `contact_id=None` handling. Handlers requiring a contact raise `ActionRequiresContactError`, run marks `errored` with the specific handler ID. | Reviewer flag (Absence §5): existing engine supports null contact, but not every action node tolerates it. |
| Cron validation | **`croniter` parse + `_get_next()` sanity + computed inter-fire ≥ 5min + 5-field-only + no seconds + reject if next fire > now + 5y.** | Reviewer flag (Attacker C1, Architect §8). String-match `* * * * *` was insufficient. |
| Cron on-load re-validation | **Every sweep-load re-parses `config_json`.** 500ms hard timeout on compute. On raise or timeout → row auto-deactivates + audit event. | Reviewer flag (Attacker H4): DB could be mutated by import/seed/repair paths bypassing API validation. |
| Max active schedules per org | **500** (soft cap, configurable in `config.env`) | Runaway guard, not competitor parity. Well above real operator needs. |
| Max fires per hour per org | **1000** (soft cap, configurable). Skip + `schedule.rate_limited` audit event when exceeded; row NOT deactivated (transient). | Reviewer flag (Attacker C1, H6): 500 schedules × 60/min = 30k fires/min. Fire budget prevents cluster+billing DoS. |
| Consecutive empty fires | **Auto-deactivate after 20** + notify owner. | Reviewer flag (Attacker M3): schedule that always resolves to empty audience is either misconfigured or a noise-DoS. |
| Beat cadence | **60s** (matches `sweep_waits`). Documented precision `±60s, never earlier than target`. | Existing operational primitive. Sub-minute revisit is a separate design. |
| Cross-org write-path check | **`get_workflow_by_id_and_org(workflow_id, current_user.org_id)` FIRST in every service method; 404 (not 403) on mismatch.** | Reviewer flag (Attacker C2): RLS-on-insert is a mechanism, not a design. Explicit check. |
| Mass-assignment shield | **Separate `ScheduleCreate` / `ScheduleUpdate` / `SchedulePause` schemas.** Server-owned fields rejected if in payload. `active` toggled only via dedicated pause/resume endpoints, not PATCH. | Reviewer flag (Attacker H5): `runs_completed=0` reset attack, `next_run_at="1970"` bypass. |
| Optimistic lock | **`If-Match: <updated_at ISO>` header required on PATCH; 409 on mismatch.** | Reviewer flag (Attacker M2, Architect §11): reviewers agreed LWW is wrong for this surface. |
| Deactivation reason column | **`deactivation_reason` enum on schedule row**: `null | manual | ended | max_runs | end_at | consecutive_empty | recurrence_timeout | contact_deleted | admin_edit_past_end_at`. | Reviewer flag (Attacker H2): silent deactivation invisible in list. Distinct states surface in UI. |
| Deactivation notification | **Email workflow owner** on any deactivation with `deactivation_reason IN ('manual', 'admin_edit_past_end_at', 'consecutive_empty', 'recurrence_timeout', 'contact_deleted')`. Natural exhaustion (`ended`, `max_runs`, `end_at`) is expected — no email. | Reviewer flag (Attacker H2): sabotage detection. |
| Contact merge/delete cascade | **On merge**: FK repoints to surviving contact. **On delete**: schedule deactivates with reason `contact_deleted` + audit event. | Reviewer flag (Absence §1): audience-parent mutation. |
| Orphan-run reaper | **Sweep's second responsibility**: `pending` runs > 1h without worker lock → `errored` with `error_reason='orphaned_pending'`. | Reviewer flag (Absence §3): sweep-crash-mid-commit. |
| Audit fields on runs | **Add `trigger_kind`, `trigger_source_id`, `triggered_by_user_id` to `tbl_workflow_runs`** in Step 1 migration. Backfill existing rows with `trigger_kind='event'`. | Reviewer flag (Attacker M5): audit-shape ambiguity, "who fired this" not answerable. |
| RLS-in-Celery | **Sweep sets `SET LOCAL app.current_org_id` per row** before `engine.start_run`. Query uses explicit `org_id` join filter as belt-and-braces. | Reviewer flag (Attacker H1, Absence §5). |
| Per-row savepoint on sweep | **Yes.** Each row's dispatch is a savepoint; raise → row auto-deactivates + audit event, batch continues. | Reviewer flag (Attacker H1): poison-row crash loop. |
| Schedule-config edit while active | **Recompute `next_run_at` on save; reset `consecutive_empty_fires` to 0.** | User expects the new cadence to take effect; a config edit is a signal the operator is watching. |
| Pausing a schedule | **`active = false`**, `next_run_at` frozen. Pausing does NOT pause the workflow's event trigger — they are independent. | Additive model. |
| Deleting the parent workflow | **`ON DELETE CASCADE`** on schedule rows. Existing workflow soft-delete already covered (sweep filter). | No orphaned schedules. |
| Frontend save | **Workflow-status-aware.** A `draft` workflow can have a schedule attached but sweep never fires (checks `workflow.status = 'active'`). | Matches existing draft-doesn't-enrol behaviour. |
| Seeded workflows schedulable | **Yes — no special-casing.** Seed process does not attach a schedule; user opts in per workflow. | Manager ask 2026-08-05. |
| Multiple schedules per workflow | **Allowed.** Each schedule row is independent (separate `next_run_at`, `active`, audit trail). | "9am daily + 5pm weekly on same workflow" is a real ask. |
| Schedule + event trigger firing same second | **Both enrol, both dedup independently** via `trigger_event_id`. Event's key = `event_id`; schedule's key = server-generated `schedule_run_uuid`. Different keyspaces. | No cross-contamination; `send_guard` still owns per-recipient dedup. |
| Preview endpoint | **Rate-limited** (per-user, 10 req/s); computed cron previews share the 500ms croniter timeout wrapper; no keystroke-preview server round-trip (client debounce). | Reviewer flag (Attacker L1). |
| Repair job for orphans | **Scheduled Celery task, not raw `.sql`.** Runs weekly; org-scoped in service layer. | Reviewer flag (Attacker L2): raw SQL bypasses RLS. |

## Cases the plan must handle

*Highest-value § per PLANNING_RULES.md — enumerate what the requested shape does not obviously say.*

1. **Two users edit the same schedule concurrently.** `If-Match: <updated_at>` on PATCH; 409 on mismatch. First writer wins; second sees conflict + re-fetches.
2. **Two workers pick the same due schedule.** `SELECT ... FOR UPDATE SKIP LOCKED`. Only one enrols.
3. **A schedule fires while its previous run is still executing.** `concurrency_policy` decides: `forbid` (default) skips; `allow` enrols anyway; `replace` cancels in-flight + enrols new.
4. **Beat is down for 6 hours.** On recovery, sweep fires each due schedule once (with `on_missed=skip` default), then forward-computes. Regardless of `on_missed`, writes `schedule.missed_fire` audit event with miss count.
5. **Beat is down for 6 days on a weekly schedule.** `on_missed=skip` → one fire, forward compute. `on_missed=run_once` → same behaviour, explicit. `on_missed=backfill_all` → 6 fires enqueued (rate-limited to per-org fire budget).
6. **User creates a schedule with `starts_at` in the past.** Reject at API: 422 "start time is in the past".
7. **User creates a schedule with `starts_at = now + 30s`.** Accepted; next sweep (within 60s) picks it up.
8. **Cron string evaluates to "next fire in year 3000".** Reject if `next_run_at > now + 5 years`.
9. **DST spring-forward: schedule set to 02:30 daily.** croniter skips missing hour. UI notes on Cron preset help text.
10. **DST fall-back: schedule set to 01:30 daily.** croniter fires once (first occurrence). UI notes.
11. **Schedule with `contact_id` set fires; the contact was merged into another contact.** FK repoints on merge; sweep dispatches against the surviving contact.
12. **Schedule with `contact_id` set fires; the contact was deleted.** Schedule auto-deactivated with `deactivation_reason='contact_deleted'` + audit + owner notification. Never fires against a dead FK.
13. **Schedule with `contact_id=NULL` fires an action that requires a contact** (e.g. `send.email` with no recipient resolvable). Action raises `ActionRequiresContactError`; run marks `errored`; schedule keeps advancing (not deactivated — this is a workflow-config bug, not a schedule bug).
14. **Org suspended / billing lapsed.** Sweep join on `tbl_organizations` skips suspended orgs; schedules resume when org resumes.
15. **Org deleted.** `ON DELETE CASCADE` from `tbl_organizations` → `tbl_workflow_schedules`.
16. **Workflow archived while schedule active.** Sweep filter `workflow.status = 'active'` — archived workflows don't fire. Schedule row untouched (operator may un-archive).
17. **Workflow deleted while schedule active.** `ON DELETE CASCADE` drops schedule row.
18. **User sets `end_at` before `starts_at`.** Reject at API: 422 "end time must be after start time".
19. **User sets `end_at = 1970-01-01` on an active schedule (sabotage vector).** Rejected as before-starts_at OR (if starts_at also past) row deactivates immediately with `deactivation_reason='admin_edit_past_end_at'` + email to workflow owner.
20. **`max_runs = 5`; 5th run fires.** Post-fire, `active=false`, `deactivation_reason='max_runs'`, `next_run_at=NULL`. UI shows "Ended".
21. **A single schedule fires; run errors on step 1.** Run marks `errored`; schedule's `next_run_at` advances (errored runs don't block subsequent fires). Consecutive-error counter TBD — not v1, but the audit trail lets ops query.
22. **Send-node quiet-hours defers a send past the next scheduled fire.** With `concurrency_policy=forbid`, next fire skips; with `allow`, both queue (send_guard dedups at recipient level).
23. **Beat worker clock skew** (server jumps forward 10 min). One extra fire acceptable; `SKIP LOCKED` prevents double-enrolment.
24. **Cron string with seconds field.** Reject at API.
25. **6-field cron with year (Linux quartz format).** Reject at API with a clear "5-field cron only" message.
26. **A pauses schedule at 09:59:30; B edits cadence at 09:59:45; sweep fires at 10:00:00.** A's pause commits first (transaction with pessimistic row lock during the PATCH-pause endpoint). B's PATCH bumps `updated_at` → their next save without an `If-Match` re-fetch fails 409. Sweep at 10:00 sees `active=false` — no fire.
27. **A deletes workflow while B is mid-edit on schedule config.** B hits save → service loads workflow via `get_workflow_by_id_and_org` → 404 (workflow gone). B's UI shows "workflow was deleted".
28. **A transfers workflow ownership while B has config panel open.** B's save → server-side permission recheck against current owner/roles → 403 if B lost write permission.
29. **Two admins in same org both install the same seeded default workflow AND both add a "daily 9am" schedule.** Two schedules exist; both fire at 09:00. Send_guard dedups at recipient level. UI shows both schedules in the workflow detail; admin can delete one.
30. **Two orgs sweeping in same tick.** Sweep query returns rows from both orgs; per-row RLS context switch means each dispatch runs under its own org. No cross-contamination.
31. **500 concurrent POST /schedules from same org.** Cap check inside service transaction (SELECT COUNT + INSERT wrapped in row-lock on org row) prevents race past the limit.
32. **Schedule's `config_json` mutated in DB directly (bypass API) to an invalid cron.** Next sweep-load re-validates; row auto-deactivates with `deactivation_reason='recurrence_timeout'` or `'recurrence_invalid'` + audit event.
33. **`org.timezone` is NULL.** Schedule create defaults tz to UTC; UI warns operator. Backfill migration populates any NULL org.timezone to UTC as a one-time repair.
34. **`recipients.py` resolver invoked with no event payload** (scheduled runs). Since scope is single-recipient v1, resolver receives `contact_id` from the schedule row directly; no payload access. Audience-of-many is out of scope — routed to Campaigns.
35. **Sweep dies between `engine.start_run` commit and `next_run_at` advance.** Same schedule refires on next tick; orphan-run reaper eventually marks the abandoned first `pending` run as `errored` with `error_reason='orphaned_pending'`. Design accepts one duplicate fire in the worst case (idempotency at send-node still applies via `send_guard`).
36. **A run enters a 30-day wait node while its parent schedule fires every 15 minutes.** With `concurrency_policy=forbid` default: no new fires while wait-parked run is in-flight. With `allow`: bounded by `max_concurrent_runs_per_schedule = 100` (config; safety net).
37. **CSRF on schedule endpoints.** Uses existing template Bearer-auth (Authorization header). Reviewer flagged as out-of-scope for this track — noted but not addressed here.

## Tests (named-before-code, per PLANNING_RULES §6)

Every step ships tests proving the claim. Named here so coverage is planned, not discovered.

**Sweep & dispatch:**
- `test_sweep_picks_only_due_schedules`
- `test_sweep_uses_skip_locked`
- `test_sweep_per_row_savepoint_isolates_poison_row`
- `test_sweep_emits_workflow_schedule_fired_event`
- `test_sweep_calls_engine_start_run_with_schedule_uuid`
- `test_sweep_run_uuid_not_exposed_in_api_response`
- `test_orphan_pending_run_reaper_marks_errored_after_1h`

**Recurrence math:**
- `test_next_run_at_forward_from_now_after_missed_window`
- `test_daily_preset_respects_schedule_timezone`
- `test_weekly_preset_dst_spring_forward_skips`
- `test_weekly_preset_dst_fall_back_fires_once`
- `test_monthly_preset_day_31_clamps_to_last_day_of_month`
- `test_cron_recurrence_reparsed_on_sweep_load`
- `test_croniter_timeout_deactivates_row_with_reason`

**Missed-run:**
- `test_on_missed_skip_writes_missed_fire_audit_event`
- `test_on_missed_run_once_fires_one_regardless_of_miss_count`
- `test_on_missed_backfill_all_enqueues_N_within_rate_limit`

**Concurrency:**
- `test_concurrency_forbid_skips_when_previous_run_running`
- `test_concurrency_replace_cancels_inflight_and_starts_new`
- `test_concurrency_allow_enrols_new_run`
- `test_max_concurrent_runs_per_schedule_safety_net`

**Validation:**
- `test_cron_validation_computed_inter_fire_below_5min_rejected`
- `test_cron_validation_seconds_field_rejected`
- `test_cron_validation_6_field_with_year_rejected`
- `test_cron_validation_rejects_beyond_5_years`
- `test_interval_validation_below_5min_rejected`
- `test_starts_at_in_past_rejected`
- `test_end_at_before_starts_at_rejected`
- `test_timezone_whitelist_rejects_invalid`
- `test_org_timezone_null_defaults_to_utc`

**Lifecycle:**
- `test_paused_schedule_not_picked_by_sweep`
- `test_archived_workflow_schedule_not_fired`
- `test_org_suspended_schedule_not_fired`
- `test_max_runs_reached_deactivates_row_with_reason_max_runs`
- `test_end_at_reached_deactivates_row_with_reason_end_at`
- `test_delete_workflow_cascades_schedule`
- `test_delete_org_cascades_schedule`
- `test_consecutive_20_empty_fires_deactivates_row_and_notifies_owner`
- `test_admin_edit_past_end_at_deactivates_and_emails_owner`
- `test_deactivation_natural_exhaustion_does_not_email`

**Contact cascade:**
- `test_contact_merge_repoints_schedule_fk_to_survivor`
- `test_contact_delete_deactivates_schedule_with_reason_contact_deleted`
- `test_null_contact_action_that_requires_contact_errors_run_not_deactivates_schedule`

**Security & isolation:**
- `test_cross_org_schedule_create_returns_404`
- `test_cross_org_schedule_patch_returns_404`
- `test_cross_org_schedule_delete_returns_404`
- `test_cross_org_schedule_list_returns_only_own_org`
- `test_cross_org_schedule_get_returns_404`
- `test_mass_assign_runs_completed_rejected`
- `test_mass_assign_next_run_at_rejected`
- `test_mass_assign_org_id_rejected`
- `test_active_toggle_via_patch_rejected` (must use pause/resume)
- `test_permission_check_server_side_role` (non-admin POST → 403)
- `test_if_match_missing_returns_428_precondition_required`
- `test_if_match_stale_returns_409_conflict`
- `test_rls_context_set_per_row_in_sweep_dispatch`

**Caps:**
- `test_max_500_active_schedules_per_org_enforced`
- `test_max_1000_fires_per_hour_per_org_skips_with_audit`
- `test_max_500_race_prevention_under_concurrent_creates`

**Audit:**
- `test_schedule_creation_writes_audit_row`
- `test_schedule_fire_populates_run_trigger_kind_schedule`
- `test_schedule_fire_populates_run_trigger_source_id_matches_schedule_id`
- `test_migration_backfill_existing_runs_trigger_kind_event`

**Migration:**
- `test_migration_up_creates_tbl_workflow_schedules_with_partial_index`
- `test_migration_up_adds_audit_columns_to_tbl_workflow_runs`
- `test_migration_down_drops_table_and_removes_columns`
- `test_migration_no_data_loss_on_existing_workflows`

## Discovery reference

- **Existing primitives reused (per Architect §1 reuse-before-create):** `workflows.tasks.sweep_waits` (extended, not duplicated), `workflows.engine.start_run`, `workflows.compliance` (quiet hours), `workflows.actions.send` (all channels), `send_guard`, `tenants.timezone`, `contacts` FK-cascade on merge/delete.
- **Existing gap closed:** `time.daily_tick` declared in `event_catalog.py:126` never emitted. This track adds `workflow.schedule_fired` as the per-schedule fire event — a per-org daily-tick emitter can still be added later independently.
- **Competitor benchmarks (interim, unsourced — `PRODUCT_BRIEF.md` does not exist yet):**
  - **HubSpot Scheduled Workflows** — presets + cron, per-workflow tz, `on_missed` toggle exposed. **We match** (added `on_missed` after Architect §5).
  - **Zoho CRM Schedules** — presets + cron, org tz only. We're marginally better (per-schedule tz).
  - **Salesforce Scheduled Flows** — presets + cron, user tz, strict skip. We match with `on_missed=skip` default.
  - **ActiveCampaign date-based** — per-contact date-anchored triggers. **We don't ship in v1** but the schedule row's nullable `contact_id` leaves the door open (per Architect §3).
  - **k8s CronJob** — `concurrencyPolicy: Allow | Forbid | Replace`. **We match** the enum exactly.

## Files touched (rough tally across steps)

- **Backend:** `core/workflows/models.py` (+`WorkflowSchedule` + 3 enums + audit columns on `WorkflowRun`), `core/workflows/data_access.py` (+CRUD + sweep due-query + reaper query + cross-org loader), `core/workflows/service.py` (+schedule CRUD + tick + recurrence math + savepoint dispatch), `core/workflows/router.py` (+schedule endpoints + pause/resume), `core/workflows/schemas.py` (+3 schemas), `core/workflows/tasks.py` (extend `sweep_waits` + reaper task), `core/workflows/trigger_handlers.py` (subscribe `workflow.schedule_fired`), `core/events/event_catalog.py` (+`workflow.schedule_fired`), `shared/celery_config.py` (no new beat entry — sweep_waits extended), `contacts/service.py` (schedule FK repoint on merge + deactivate on delete), 1 Alembic migration (table + audit columns + org.timezone NULL backfill), `pyproject.toml` (+`croniter`), `config.env` (max-schedules + fire-budget caps).
- **Frontend:** `features/user/core/workflows/detail-page.component` (Schedule panel: list + add), `features/user/core/workflows/schedule-config.component` (new: preset picker + cron preview), `features/user/core/workflows/schedule-list.component` (new: rows with Next Run + Pause/Resume/Delete), `features/user/core/workflows/list-page.component` (Scheduled filter chip + Next Run column), `features/user/core/workflows/models.ts` (schedule types), `features/user/core/workflows/workflows.service.ts` (schedule CRUD + If-Match ETag).
- **Tests:** ~65 pytest cases across sweep/dispatch/validation/audit/tz/DST/cascade/isolation/caps + Karma cases for schedule config panel + cron preview.
- **Smoke:** manual on Ajay's Workspace — one schedule per preset, DST verification, beat-outage skip, contact-merge cascade.

## Step index

| # | Title | Status | Files | Effort |
|---|---|---|---|---|
| 1 | [Backend model + migration + DAL + `croniter` dep](step-1-backend-model-and-migration.md) | **COMPLETED** (2026-08-05, migration 0182 applied; 166 legacy runs backfilled to trigger_kind='event') | 6 | ~0.75 day |
| 2 | [Backend service + extend `sweep_waits` + dual-dispatch + null-contact action audit](step-2-backend-service-and-sweep.md) | **COMPLETED** (2026-08-05, sweep fires real schedules end-to-end; recurrence + DST + poison-row isolation verified) | 10 | ~1 day |
| 3 | [Backend API endpoints + validation + caps + cross-org check + If-Match + pause/resume](step-3-backend-api-endpoints.md) | **COMPLETED** (2026-08-06, 8 endpoints live; 16-case HTTP smoke against Ajay's org PASS) | 5 | ~0.75 day |
| 4 | [Frontend — Schedule attach panel on workflow detail + config form + cron preview](step-4-frontend-attach-panel.md) | **COMPLETED** (2026-08-06, schedules drawer + config modal + debounced cron preview live) | 8 | ~1 day |
| 5 | [Frontend — schedule list surfacing on workflows page + pause/resume/delete](step-5-frontend-list-surfacing.md) | **COMPLETED** (2026-08-06, Scheduled chip + Next Run column + Pause-all/Resume-all row actions; N+1 guard 2 SELECTs for 50-row list) | 8 | ~0.5 day |
| 6 | [Data lifecycle — contact-merge cascade + orphan-run reaper + consecutive-empty deactivation](step-6-data-lifecycle.md) | **COMPLETED** (2026-08-06, all 4 safety nets live; reaper cleaned 11 pre-existing orphans in first run) | 8 | ~0.75 day |
| 7 | [Smoke verification on Ajay's Workspace (6 presets + DST + missed-run + contact-merge)](step-7-smoke-verification.md) | **COMPLETED** (2026-08-06, 20 PASS · 0 FAIL · 7 pytest-covered SKIP against Ajay's org) | 2 (docs) | ~0.5 day |

**Total: 7 steps, ~5.25 days.**

## Sequencing — why this order matters

- **Step 1 (model + migration)** ships first — every later step imports the model. Migration adds table + audit columns + `org.timezone` NULL backfill in one atomic upgrade.
- **Step 2 (service + sweep + null-contact audit)** requires Step 1. Ships "runs at all" milestone. Null-contact action-handler audit belongs here because sweep will exercise those handlers.
- **Step 3 (API + validation + caps + If-Match)** requires Step 2. Ships CRUD.
- **Step 4 (Builder attach panel)** requires Step 3. Ships "operator can create" milestone.
- **Step 5 (list surfacing)** requires Step 4. Cosmetic + management.
- **Step 6 (lifecycle: contact-merge cascade + reaper + empty-fire deactivation)** ships AFTER Step 5 because it exercises the full stack. Could partially move earlier — reaper is Celery-only and could ship with Step 2 — but batching lifecycle in one step is cleaner for review.
- **Step 7 (smoke)** last.

**Recommended deploy sequence:** Steps 1–3 to staging, verify sweep on hand-crafted row, then 4–5 to staging, then Step 6 to staging, then smoke, then production in one deploy.

## Reverse / rollback

- Each migration has a working `downgrade`.
- Rollback: `UPDATE tbl_workflow_schedules SET active = false` (freezes fires), redeploy previous frontend (schedule panel hidden), `alembic downgrade` past Step 1 (drops table + audit columns; existing workflow rows untouched).

## Rules & conventions

- **10 non-negotiable rules (CLAUDE.md):** `org_id` + RLS on new table, `tbl_workflow_schedules` name, no `core/` → `packs/` imports, no TODOs.
- **Router → Service → DAL:** endpoints in router.py call service.py only; sweep task calls service.py; SQL only in data_access.py.
- **Pin-tests:** `test_table_name_convention.py` and `test_layered_architecture_convention.py` must pass after every step.
- **Alembic revision ID ≤ 32 chars** (per memory: 0170 incident).
- **Prettier on write** for any Angular file (per memory: pre-commit).
- **Migrations run inline** via `API\run.cmd upgrade` before stop-and-report (per memory).
- **DB efficiency:** sweep uses partial index (`WHERE active = true`); joins tenants + workflows in one statement per row batch; per-row savepoint scoped to the org context; no N+1.
- **Croniter timeout wrapper** (500ms) is a shared utility — reuse, don't inline.

## Open items (deferred, not blocking)

1. **Multi-recipient scheduled sends** → Campaigns-parity follow-up track. Existing Campaigns already schedules; extend or unify later.
2. **Recipient-local timezone sends** — per-contact tz field required first.
3. **Date-anchored triggers** (e.g., "3 days before renewal_date") — schedule row's nullable `contact_id` leaves the door open; per-contact-per-schedule fan-out logic is the missing piece.
4. **`time.daily_tick` emitter** — independent, orthogonal.
5. **Cron human-readable translator** ("Every day at 9am") in Builder — nice-to-have.
6. **Bulk schedule management** ("pause all") — v2.
7. **Consecutive-error auto-deactivation** (parallel to consecutive-empty) — deferred; audit trail lets ops query manually in v1.
8. **Sub-minute precision** — revisit sweep cadence if real ask appears.
9. **CSRF hardening on schedule endpoints** — reviewer flag; template-wide, not this-track scope.
10. **Retention policy for `tbl_workflow_runs`** — reviewer flag (Absence §4). Row-growth model documented as a Phase-6 ops concern; no auto-purge in v1 (row growth is bounded by per-org fire budget × orgs × time).
