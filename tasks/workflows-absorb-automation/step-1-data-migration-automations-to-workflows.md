# Step 1 — Data migration: existing automations → workflows

**Goal:** For every org, migrate every row in `tbl_automations` into a matching single-step workflow (`tbl_workflows` + one `tbl_workflow_nodes` action). Preserve trigger, action, channel, template, delay, recipient resolver, and conditions. Soft-disable the source automation so the two engines never fire the same event. Add a bidirectional FK column (`tbl_automations.migrated_to_workflow_id`) so redirects and rollbacks can look up the mapping.

**Status:** Pending

**Depends on:** `core/automation/` (live), `core/workflows/` (live, Step 20 shipped)

---

## Scope

In-scope:
- Alembic **schema** migration: add `tbl_automations.migrated_to_workflow_id` (nullable UUID FK to `tbl_workflows.id`, `ON DELETE SET NULL`).
- Alembic **data** migration: idempotent SQL that walks every org and every automation row.
  - For each `tbl_automations` row: create one `tbl_workflows` row (`is_active` = matches source `enabled`, `is_system_default = false`, category `Migrated Automation`, description `Migrated from automation "<name>"`).
  - Attach one `tbl_workflow_nodes` action node with `node_type = "send.<channel>"`, `config = {template_id, recipient_resolver, recipient_resolver_config, conditions}`.
  - If source's `delay_seconds > 0`: prepend a `flow_control.wait` node with `config = {seconds: <delay_seconds>}`.
  - Attach one `tbl_workflow_triggers` row with the source's event key.
  - Set `tbl_automations.enabled = false` on the source row (soft-disable).
  - Set `tbl_automations.migrated_to_workflow_id = <new workflow id>`.
- Guard: skip rows already migrated (`migrated_to_workflow_id IS NOT NULL`) → migration is re-runnable.
- Guard: skip inserting workflow rows whose name already exists per-org (dedupe on `(org_id, lower(name))`) — treats a pre-existing operator-created workflow with the same name as the "target" and links the automation to it. Logs the mapping instead.
- Downgrade: reverse — for every `tbl_automations` row with `migrated_to_workflow_id` set, delete the mirror workflow + its nodes + trigger, restore `enabled = true` on the automation, clear the FK. Then drop the column.

Out of scope:
- Frontend changes (Step 3).
- Seed changes for new orgs (Step 2).
- Retry policy on workflow nodes (open item — future track).
- Migrating `tbl_automation_runs` history — legacy runs stay on the automation tables.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/automation/models.py` | edit — add `migrated_to_workflow_id: Mapped[UUID \| None]` column, FK to `tbl_workflows.id`, `ondelete="SET NULL"` |
| `api/alembic/versions/<ts>_add_migrated_to_workflow_id.py` | **NEW** schema migration — adds the column + FK + index |
| `api/alembic/versions/<ts>_backfill_automations_to_workflows.py` | **NEW** data migration — the walker + writer described above |
| `api/tests/workflows/test_absorb_automation_migration.py` | **NEW** — 6 pytest cases: creates workflow mirror with correct trigger/action/channel/template/recipient; delay>0 inserts wait node; source automation ends disabled with FK set; re-run is a no-op; downgrade restores state; per-org isolation (Org A's migration doesn't touch Org B) |
| `api/src/app/core/automation/data_access.py` | edit — add `set_migrated_to(session, *, automation_id, workflow_id)` and `find_by_migrated_workflow_id(session, *, workflow_id)` helpers (used by Step 3 redirect resolver) |

**~5 files. ~450 lines** (mostly migration SQL + test fixtures).

## Migration keys & mappings

| Source column (`tbl_automations`) | Target |
|---|---|
| `name` | `tbl_workflows.name` |
| `description` | `tbl_workflows.description` (prefixed `[migrated] ` if source had no description) |
| `event_key` | `tbl_workflow_triggers.event_key` |
| `channel` (email/sms/whatsapp/…) | node_type = `send.<channel>` |
| `template_id` | node config `template_id` |
| `recipient_resolver` | node config `recipient_resolver` |
| `recipient_resolver_config` (JSONB) | node config `recipient_resolver_config` |
| `conditions` (JSONB) | trigger row `conditions` |
| `delay_seconds` (int) | if >0: inserted `flow_control.wait` node before the send |
| `enabled` (bool) | `tbl_workflows.is_active` |
| `org_id` | `tbl_workflows.org_id` (same value) |
| — | `tbl_workflows.is_system_default = false` |
| — | `tbl_workflows.category = 'Migrated Automation'` |
| — | `tbl_workflows.created_by_user_id = tbl_automations.created_by_user_id` |
| — | `tbl_workflows.source = 'migrated_from_automation'` (new source enum value if not present) |

## Plan

1. **Schema migration** — add the FK column with `nullable=True`, `index=True`. Downgrade drops the column.
2. **Data migration** — pure `op.execute()` raw SQL. No ORM (Alembic best practice — models can drift). Structure:
   - `WITH inserts AS (INSERT INTO tbl_workflows … SELECT … FROM tbl_automations WHERE migrated_to_workflow_id IS NULL AND … RETURNING id, name, org_id)` — batched insert
   - Join back to source rows on `(org_id, name)` to populate `tbl_workflow_nodes`, `tbl_workflow_triggers`, then `UPDATE tbl_automations SET enabled=false, migrated_to_workflow_id=…`
   - Wrapped in a single txn per org (Alembic runs the whole migration in a txn already).
3. **Idempotency** — every INSERT gated by `WHERE NOT EXISTS` / `ON CONFLICT DO NOTHING`. Re-running the migration is a no-op.
4. **DAL helpers** — thin lookups for the redirect resolver in Step 3.
5. **Tests** — small `pytest` module using `alembic_config.stamp('base')` fixtures to prove the mapping.

## DB changes / migrations

Two Alembic revisions:

1. `<ts>_add_migrated_to_workflow_id` — schema, adds column + FK + index. **Revision ID ≤ 32 chars** per `feedback_alembic_revision_id_length.md`.
2. `<ts>_backfill_automations_to_workflows` — data. Depends on #1. Idempotent.

Run via `API\run.cmd upgrade` per `feedback_execute_migrations_inline.md`.

## Tests

6 pytest cases in `test_absorb_automation_migration.py`:

- `test_migration_creates_workflow_mirror_with_matching_trigger_and_action` — insert 1 automation, run migration, assert 1 workflow row + 1 action node + 1 trigger row exist with all fields matching.
- `test_delay_seconds_inserts_wait_node_before_send` — insert automation with `delay_seconds=3600`, assert workflow has 2 nodes (wait, send) in the right order.
- `test_source_automation_disabled_and_fk_set` — post-migration, source's `enabled=false` and `migrated_to_workflow_id=<workflow.id>`.
- `test_migration_is_idempotent` — run twice, assert exactly 1 workflow row (not 2).
- `test_downgrade_restores_original_state` — upgrade then downgrade, assert source `enabled=true` restored, workflow row gone, FK column absent.
- `test_multi_tenant_isolation` — seed 2 orgs each with 3 automations, run migration, assert Org A's 3 workflows have `org_id=A`, Org B's 3 have `org_id=B`, no cross-contamination.

## Smoke (post-migration, before Step 2)

```
1. Backup DB (pg_dump on staging — feedback_execute_migrations_inline handles command).
2. API\run.cmd upgrade head
3. Log into Ajay's Workspace (41f9ede9-41b3-44ce-b489-3004566d4068).
4. SELECT COUNT(*) FROM tbl_automations WHERE org_id='…' AND enabled=true;    → 0
5. SELECT COUNT(*) FROM tbl_automations WHERE org_id='…' AND migrated_to_workflow_id IS NOT NULL;   → N (N = count of automations that existed)
6. SELECT COUNT(*) FROM tbl_workflows WHERE org_id='…' AND category='Migrated Automation';   → N
7. Fire a lead.created event via /api/v1/leads → assert exactly 1 workflow_run inserted, exactly 0 new automation_runs.
8. Fire a user.signed_up (register a fresh test user in a burner org) → same: 1 workflow_run, 0 automation_runs.
```

If step 7 or 8 shows a duplicate run, **STOP** — the automation dispatcher is still matching. Investigate `automation.service.match_triggers` for whether it respects `enabled=false`. (It does per current audit — but verify.)

## Raw SQL snippet for report

Migration outputs the mapping so operator can see what happened per-org:

```sql
SELECT
    o.name AS org,
    a.name AS automation_name,
    a.event_key,
    a.channel,
    w.id AS new_workflow_id,
    a.enabled AS still_enabled
FROM tbl_automations a
JOIN tbl_organizations o ON o.id = a.org_id
JOIN tbl_workflows w ON w.id = a.migrated_to_workflow_id
ORDER BY o.name, a.name;
```

## Risks

- **Duplicate sends during migration window.** The data migration runs inside a single Alembic txn. Between `INSERT INTO tbl_workflows … is_active=true` and `UPDATE tbl_automations SET enabled=false`, both engines could theoretically fire on the same event → duplicate. **Mitigation:** the migration flips `enabled=false` FIRST (before creating the workflow mirror), so at every intermediate point the automation is off. Trade-off: a brief window where the trigger is dead, but no dupes.
- **`ON CONFLICT DO NOTHING` semantics.** If an operator has manually pre-created a workflow with the same name as an automation, the migration skips creation and links to the existing workflow. Report step above surfaces this so operator can audit.
- **Alembic revision ID length.** Both revision IDs must be ≤ 32 chars per `feedback_alembic_revision_id_length.md`. Suggested: `0210_add_migrated_wf_fk`, `0211_backfill_autos_to_wf` (23 and 24 chars).

## Self-check (10 rules · layering · reuse · DB efficiency · tooling-clean)

- ✓ `core` never imports from `packs`. N/A.
- ✓ `org_id` on every new row. Both `tbl_workflows` and `tbl_workflow_nodes` already require it; migration writes source `automation.org_id` on every insert.
- ✓ `tbl_` prefix. `migrated_to_workflow_id` is a column on existing `tbl_automations`; no new tables.
- ✓ Custom fields — N/A.
- ✓ Sidebar / permissions — N/A (Step 3).
- ✓ Pack manifest untouched.
- ✓ Step size — 5 files, ~450 lines. Under threshold.
- ✓ Stop-and-report.
- ✓ No TODOs / no commented-out code.
- ✓ Layering — migration is raw SQL (Alembic convention); DAL helpers in `data_access.py`; no `db.commit()` outside `service.py`.
- ✓ Reuse — extends existing `data_access.py`; no near-duplicates.
- ✓ DB efficiency — batched inserts, no per-row Python loop; single txn per Alembic run.
- ✓ Tooling — `ruff format`, `ruff check`; migration passes `test_table_name_convention` (no new plain-named tables) and `test_layered_architecture_convention` (no SQL in router/service).

## Stop & report

```
Step 1 — Data migration: existing automations → workflows
Files: 5
Verify:
  - Alembic upgrade + downgrade both succeed on staging DB.
  - Ajay's Workspace shows N migrated workflows, 0 enabled automations.
  - Firing lead.created → exactly 1 workflow_run row, 0 automation_runs.
Tests: 6 pytest cases in test_absorb_automation_migration.py.
Migration SQL: <inline in step file>
Self-check: 10 rules · layering · reuse · DB efficiency · tooling-clean — all pass.
Awaiting your "proceed".
```
