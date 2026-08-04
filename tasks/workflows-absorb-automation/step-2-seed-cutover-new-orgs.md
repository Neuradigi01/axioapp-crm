# Step 2 — Seed cutover: new orgs get workflows only

**Goal:** When a brand-new org is created, seed the 10 preset automations as single-step **workflows** instead of automations. Register the 10 as templates in `core/workflows/gallery/` so they also show up in the Templates tab. Keep `core/automation/seeds.py` code intact but stop calling it from `core/tenants/service.create_organization`.

**Status:** Pending

**Depends on:** Step 1 (migration already turned existing orgs' automations off, so seed cutover on new orgs finalises the "no automations anywhere" state).

---

## Scope

In-scope:
- **10 new workflow seeds** in `core/workflows/seeds.py` — one per current preset automation. Each is a single-step workflow (trigger → 1 send action), name matches source ("User Welcome", "Lead Confirmation", "Appointment Booked", "Appointment Reminder 24h", "Appointment Reminder 1h", "Invoice Sent", "Invoice Paid", "Invoice Overdue 7d", "Contact Birthday", "Lead Stale 30d"). All seeded with `is_active=true` (transactional behaviour preserved). All idempotent on `(org_id, lower(name))`.
- **10 new gallery entries** in `core/workflows/gallery/` — each preset workflow also registered as a template so operators can clone it if they delete or modify the seeded copy.
- Edit `core/tenants/service.create_organization`: remove the call to `automation.seeds.install_default_org_seeds` (or replace with the workflow-seed equivalent). Add call to a new `workflows.seeds.install_default_org_workflows(session, org_id=…)`.
- Keep `core/automation/seeds.py` file + functions — **do not delete**. Un-called is fine. Documented in a header comment as "retained for future re-use — no longer wired at org creation as of 2026-08-04".
- **Backfill migration** — for any existing org that (a) went through Step 1 (has migrated workflows) and (b) is somehow missing one of the 10 preset workflows (e.g. operator deleted an automation before migration), install the missing preset as a workflow. Belt-and-braces.

Out of scope:
- Frontend UI (Step 3).
- Retry-policy parity.
- Deleting `core/automation/seeds.py` — future track.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/workflows/seeds.py` | edit — add 10 `seed_<name>_workflow(session, *, org_id, template_id)` idempotent inserters + `install_default_org_workflows(session, *, org_id)` orchestrator |
| `api/src/app/core/workflows/gallery/preset_automations.py` | **NEW** — 10 gallery entries mirroring the seed shapes, registered in `gallery/__init__.py` |
| `api/src/app/core/workflows/gallery/__init__.py` | edit — register the new preset-automation gallery entries |
| `api/src/app/core/tenants/service.py` | edit — swap `automation.seeds.install_default_org_seeds` → `workflows.seeds.install_default_org_workflows` |
| `api/src/app/core/automation/seeds.py` | edit — add header comment marking function as retained-but-unused; no functional change |
| `api/alembic/versions/<ts>_backfill_preset_workflows.py` | **NEW** data migration — for every org, install any of the 10 preset workflows missing from `tbl_workflows` |
| `api/tests/workflows/test_preset_workflow_seeds.py` | **NEW** — 8 pytest cases (one per seed helper + orchestrator idempotency + backfill idempotency) |
| `api/tests/tenants/test_create_org_installs_workflow_seeds.py` | **NEW** — 3 pytest cases (new org gets 10 workflows, does not get any new automations, seeds run inside tenant creation txn) |

**~8 files. ~500 lines.**

## Plan

1. **10 workflow seed helpers.** Each mirrors the shape of the corresponding automation seed: same trigger event, same recipient resolver, same template_id (seed calls `templates.seeds.seed_<name>_template` first). Difference: writes to workflow tables, single-step DAG (or wait+send if `delay_seconds>0`).
2. **Orchestrator.** `install_default_org_workflows(session, *, org_id)` calls all 10 seed helpers + the existing `templates.seeds.install_default_org_templates` chain. Returns `{workflow_ids: [...], template_ids: [...]}` for audit logs.
3. **Gallery entries.** Each of the 10 also appears in the Templates tab so operators can clone / restore. Gallery entries include description + preview thumbnail (reuse whatever chrome existing gallery entries use).
4. **Tenant service swap.** One-line change: `install_default_org_seeds` → `install_default_org_workflows`. Call site stays inside the org-creation txn.
5. **Backfill migration.** Walk every org, check for missing preset workflows, install any missing. Non-destructive — only inserts.
6. **Tests.** Per-seed unit tests + integration test on `create_organization`.

## DB changes / migrations

One data migration: `<ts>_backfill_preset_workflows` (revision ID ≤ 32 chars — suggested `0212_backfill_preset_wf`, 22 chars).

No schema change.

## Tests

11 pytest cases across two files:

**`test_preset_workflow_seeds.py`** (8 cases):
- `test_seed_user_welcome_workflow_creates_single_step`
- `test_seed_appointment_reminder_24h_workflow_creates_wait_then_send` (delay > 0 case)
- `test_seed_lead_confirmation_workflow_excludes_bulk_import_condition` (condition preservation)
- `test_seed_helpers_are_idempotent_on_name_match`
- `test_install_default_org_workflows_creates_all_ten`
- `test_install_default_org_workflows_is_idempotent`
- `test_all_seeded_workflows_start_active` (is_active=true, matches transactional behaviour)
- `test_gallery_registers_ten_preset_entries`

**`test_create_org_installs_workflow_seeds.py`** (3 cases):
- `test_create_organization_installs_ten_workflows_and_zero_automations`
- `test_workflow_seed_rollback_on_org_creation_failure` (same-txn guarantee)
- `test_backfill_migration_installs_missing_preset_workflows_on_existing_orgs`

## Smoke (post-Step-2)

```
1. Register a fresh test tenant via /api/v1/auth/register (email: qa-cutover-01@example.com).
2. SELECT COUNT(*) FROM tbl_workflows WHERE org_id=<new_org_id>;         → 15 (10 presets + 5 non-preset seeded workflows from Step 20)
3. SELECT COUNT(*) FROM tbl_automations WHERE org_id=<new_org_id>;       → 0
4. SELECT name, is_active FROM tbl_workflows WHERE org_id=<new_org_id> AND name IN ('User Welcome','Lead Confirmation',…);
   All 10 present. All is_active=true.
5. Confirm the auto-fired welcome email arrives in the new Owner's inbox within 60s (Celery worker cycle).
6. Log into /user/workflows for the new org → all 10 visible in "My Workflows".
7. Open the Templates tab → 10 preset automations visible as clonable templates.
```

## Raw SQL for report

Post-Step-2, run for every org:

```sql
SELECT
    o.name AS org,
    COALESCE(SUM(CASE WHEN name IN (…10 names…) THEN 1 ELSE 0 END), 0) AS preset_workflows_present,
    COALESCE(SUM(CASE WHEN a.enabled THEN 1 ELSE 0 END), 0) AS active_automations
FROM tbl_organizations o
LEFT JOIN tbl_workflows w ON w.org_id = o.id
LEFT JOIN tbl_automations a ON a.org_id = o.id
GROUP BY o.name
ORDER BY o.name;
```

Every row should show `preset_workflows_present = 10` and `active_automations = 0`.

## Risks

- **Test-suite drift.** Existing automation tests (in `automation-engine/` step 5+) assume `install_default_org_seeds` still runs on `create_organization`. Those tests will fail. Fix: update the automation tests to call `install_default_org_seeds` directly in setup (not via `create_organization`), or mark them `@pytest.mark.skip(reason="Seed no longer wired at org creation")`. Choose the first — keeps the coverage.
- **Template variable drift.** The preset workflow seed installs a template + a workflow that references it. If the template's variables (e.g. `{{ user.full_name }}`) drift over time, the seed helper must be kept in sync with the template. Mitigation: seed helpers call `templates.seeds.seed_<name>_template(...)` first and use its returned id — so template + workflow always match.
- **Backfill on production orgs where the operator has deleted a preset automation.** Migration would install a preset workflow they'd previously chosen to remove. Mitigation: backfill only installs presets that were **originally** part of the automation seed AND haven't already been migrated in Step 1. Rows the operator disabled will still have `migrated_to_workflow_id` set (from Step 1) → skipped. Rows the operator DELETED (rare — automation UI probably only has disable, not delete) → backfill installs them, arguably wrong. Trade-off: keep it simple (backfill installs), document, provide a way to disable per-workflow.

## Self-check (10 rules · layering · reuse · DB efficiency · tooling-clean)

- ✓ `org_id` on every seed row.
- ✓ `tbl_` prefix — no new tables.
- ✓ Custom fields — N/A.
- ✓ Sidebar / permissions — N/A (Step 3).
- ✓ Pack manifest — untouched.
- ✓ Step size — 8 files, ~500 lines. Within threshold.
- ✓ Stop-and-report.
- ✓ No TODOs.
- ✓ Layering — new code lives in `core/workflows/seeds.py` (a helper module, allowed to call DAL); `create_organization` in `core/tenants/service.py` calls the seed orchestrator (Service → Service, allowed).
- ✓ Reuse — seed helpers piggyback on existing `seed_<name>_template` chain; no re-implementation of template creation.
- ✓ DB efficiency — orchestrator does batched inserts; backfill migration walks orgs once with a single UPSERT per preset.
- ✓ Tooling clean.

## Stop & report

```
Step 2 — Seed cutover: new orgs get workflows only
Files: 8
Verify:
  - Alembic upgrade succeeds. Backfill installs any missing presets across all existing orgs.
  - Fresh org registration: 10 preset workflows installed, 0 automations, welcome email fires from workflow_run.
  - All 10 presets visible in Templates tab as clonable.
Tests: 11 pytest cases across two files.
Migration SQL: <inline>
Self-check: all pass.
Awaiting your "proceed".
```
