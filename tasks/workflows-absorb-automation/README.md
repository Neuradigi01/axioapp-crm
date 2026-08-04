# Workflows Absorb Automation

Merge the `core/automation/` module into `core/workflows/` from the operator's perspective. Every automation becomes a single-step workflow (trigger + one action node); the Automations sidebar entry and routes disappear; new orgs seed workflows only. `core/automation/` **code stays in place** — this is a data + UI cutover, not a code deletion.

## Why this track exists

Manager directive 2026-08-04: "We want to achieve all automation functionality through the Workflows module … hide the Automations module from the UI, but do not delete or remove its code, as we may reuse or merge it later."

Rationale — the parity check (see § Discovery below) confirms every automation is expressible as a 1-step workflow. Two separate lists ("Automations" for single-step, "Workflows" for multi-step) is a distinction the operator doesn't care about — matches HubSpot Workflows / Zoho Workflow Rules / Salesforce Flow / MS Power Automate consolidation. `core/email_sequences/` was absorbed into workflows the same way in 2026-06-30 (Step 20 of workflows track). Same pattern applied here.

## What this track does

- **Data migration** — every row in `tbl_automations` (across every org, seeded + user-created) becomes a matching single-step workflow in `tbl_workflows`. Trigger, action, channel, template_id, delay, recipient_resolver, conditions all preserved. Original automation rows soft-disabled (`enabled = false`) so both engines aren't firing the same event → **no duplicate sends** at any point.
- **Bidirectional FK mapping** — new `tbl_automations.migrated_to_workflow_id` column lets us route bookmarked deep-links (`/user/automations/:id` → `/user/workflows/:new_id`) and gives us a clean reversible downgrade path.
- **New-org seed cutover** — `install_default_org_seeds` no longer installs the 10 preset automations. Instead installs the same 10 as single-step workflows (via new `workflows/seeds.py` entries). Preserves the "active-on-seed" behaviour transactional sends need.
- **Frontend hide** — Automations sidebar entry removed, `/user/automations/*` routes redirect via a resolver that looks up `migrated_to_workflow_id` and forwards to the matching workflow. Angular feature module code left in place (unrouted).
- **Smoke on existing org** — Ajay's Workspace (`41f9ede9-41b3-44ce-b489-3004566d4068`) verified end-to-end.

## What this track does NOT do

- **Delete `core/automation/` code.** Manager explicit: "do not delete or remove its code, as we may reuse or merge it later." Backend router / service / DAL / models / seeds / event dispatcher all stay. Only the dispatcher's behaviour changes (via `enabled=false` rows) — no code deletion.
- **Unify the two engines.** `automation.dispatcher` and `workflows.trigger_handlers` remain separate subscribers on the shared event bus. Automation subscriber becomes a no-op in practice (all rows disabled) but stays wired. A future track can consolidate the engines.
- **Add retry parity to workflows.** Automations have Celery retry (3 attempts, exp backoff 30s→600s); workflows engine has no retry. Migrated sends lose retry behaviour on transient failures. Flagged in **Open items** below — a follow-up track can add workflow-node retry parity. Not blocking for the cutover; industry practice (HubSpot, Zoho) is per-node retry policy configurable on the send node, and the current transient-failure rate on WhatsApp/email is low enough that operating without retry for a short window is acceptable.
- **Migrate `tbl_automation_runs` history.** Old run history stays queryable via a legacy `Automation Run History` page (also hidden but kept). New runs write to `tbl_workflow_runs`. History gaps in the UI are acceptable — no live production data to preserve pre-launch.
- **Consolidate `tbl_automation_suppressions` / `tbl_email_bounce_events`** into the workflow tables. These are shared compliance tables that both engines already read; no consolidation needed.

## Locked decisions

| Decision | Value | Why |
|---|---|---|
| Existing orgs migrated? | **Yes, all of them** (via backfill migration) | Manager 2026-08-04: "and this should be applied to all the existing organizations ok" |
| Old automation rows | **Soft-disabled** (`enabled=false`), retained | Reversible; keeps run-history joinable; audit trail preserved |
| New-org seed | **Workflows only.** 10 preset triggers seed as single-step workflows | Prevents parallel worlds; new orgs get one unified list |
| Preset seed behaviour | **Active-on-seed** (transactional sends fire immediately) | Preserves current behaviour — Welcome emails, Birthday WhatsApps, Appointment Reminders "just work" for a new org |
| Automation code | **Kept in place**, no deletion | Manager explicit directive |
| `core/automation/` sidebar route | **Redirected** via resolver, not 404'd | Preserve bookmarks and links from templates/docs/audit-log entries |
| Automation dispatcher subscriber | **Left wired** to event bus | All triggers disabled = no matches = effective no-op. Cleaner than editing dispatcher code. |
| Duplicate-send prevention | **Row-level `enabled=false`** on old automations | Simpler than adding a global feature-flag; already the mechanism the dispatcher checks |

## Open items (deferred, not blocking)

1. **Workflow retry parity.** Migrated sends lose Celery retry on transient failure. Follow-up track can add per-node retry policy (matching automation's 3-attempt exp backoff). Not in this track.
2. **Legacy run-history UI.** `tbl_automation_runs` remains readable but has no UI entry. Decide later whether to build a "Legacy Automation Runs" archive view or drop the tables entirely after a retention window.
3. **Automation dispatcher removal.** Once every org has all-disabled automations for N days without incident, a follow-up can unregister the automation subscriber entirely. Deferred until confidence built.
4. **Test-suite cleanup.** Automation test files still exercise the seeded triggers. Leave them passing (they still work — engine intact); rewrite when the eventual code-deletion track lands.

## Discovery reference

Parity check 2026-08-04 (agent report):
- **Triggers: 100% parity** — both engines subscribe to the same `core.events.event_catalog` (30 event types). Every automation trigger has a workflow trigger equivalent.
- **Send actions: 100% parity** — workflows has all 7 channels (email, sms, whatsapp, facebook_messenger, instagram_direct, push_notification, slack) plus 34 more action types. Migration is straightforward — automation's single-channel `channel` + `template_id` becomes a workflow `send.<channel>` action node with `template_id` in its config.
- **Schema deltas:** automation-only columns (`channel`, `template_id`, `delay_seconds`, `recipient_resolver`, `recipient_resolver_config`) all fit inside workflow action-node config JSONB. `delay_seconds` becomes a `flow_control.wait` node inserted before the send action (only when >0). No data loss.
- **Engine architecture:** **critical finding** — both dispatchers listen to the same event bus. Any live automation whose workflow-mirror is also active = **duplicate send**. Migration must soft-disable each automation in the same transaction that creates its workflow mirror. Zero-window cutover per row.
- **`is_seeded` flag:** neither table has one. Seeded rows identified by exact name match against the 10 known names. Migration doesn't need to distinguish; migrates every row.

## Files touched (rough tally across steps)

- Backend: `core/automation/models.py` (+1 col), `core/tenants/service.py` (seed swap), `core/workflows/seeds.py` (+10 seeds), `core/workflows/gallery/*` (register 10 templates), 2 Alembic migrations
- Frontend: `features/user/core/layout/sidebar.ts` (remove entry), `features/user/user.routes.ts` (redirects), `features/user/core/automation/**` (leave in place, unrouted)
- Tests: ~15 pytest cases across migration/seed/dispatcher/redirect
- Smoke: manual on Ajay's Workspace + fresh registration

## Step index

| # | Title | Status | Files | Effort |
|---|---|---|---|---|
| 1 | [Data migration — existing automations → workflows](step-1-data-migration-automations-to-workflows.md) | Pending | 5 | ~1 day |
| 2 | [Seed cutover — new orgs get workflows only](step-2-seed-cutover-new-orgs.md) | Pending | 6 | ~0.5 day |
| 3 | [Frontend hide — sidebar + redirect resolver](step-3-frontend-hide-automations.md) | Pending | 5 | ~0.5 day |
| 4 | [Smoke verification across existing + fresh orgs](step-4-smoke-verification.md) | Pending | 0 | ~0.25 day |

**Total: 4 steps, ~2.25 days.**

## Sequencing — why this order matters

Every step is deploy-safe on its own. The one hard rule: **Step 1 (data migration) MUST run before or with the same deploy as Step 2 (new-org seed cutover)**, otherwise:
- New orgs registered between Step 1 and Step 2 would get seeded automations that never fire (dispatcher no-op) → seeded seeded workflows would come from Step 2 → workflow list would be empty for those orgs until backfill re-run.

Steps 3 and 4 can ship independently after Steps 1–2. Frontend hide before backend migration would strand users on redirects with nothing on the other end.

**Recommended deploy sequence for production:** Steps 1 + 2 in the same deploy → verify on staging → deploy Step 3 → run Step 4 smoke on Ajay's Workspace → announce.

## Reverse / rollback

Each step's Alembic migration has a working downgrade. Rollback path:
1. Deploy previous frontend (Automations sidebar entry restored).
2. `alembic downgrade` past Step 2's seed swap.
3. `alembic downgrade` past Step 1's data migration — for each workflow with a `migrated_from_automation_id` set, the workflow row deletes, the source automation row's `enabled` restores to its pre-migration value, the `migrated_to_workflow_id` FK clears.
4. `core/automation/` dispatcher was never modified — resumes firing on the re-enabled rows.

## Rules & conventions

- **10 non-negotiable rules** (CLAUDE.md): every new column/row has `org_id`, every workflow seed carries the source org's tenant, RLS respected.
- **Router → Service → DAL** (CLAUDE.md): the migration script uses raw SQL (Alembic op.execute) — no service-layer bypass. Any runtime code changes stay layered.
- **`tbl_` prefix** for the new column (`tbl_automations.migrated_to_workflow_id`).
- **Preserve legacy naming.** No DOM class renames. Angular `features/user/core/automation/` folder untouched — only its route is dropped.
