# Restore Automations Module (Runbook)

**Purpose:** Reverse the cutover done by this track and restore the platform to its **pre-2026-08-04 state**, where `core/automation/` was a first-class module with its own sidebar entry, live triggers, and independent dispatcher. Use this doc if you decide that the automation module should come back — either fully (production) or temporarily (staging spike to test something).

**Written:** 2026-08-04 (drafted alongside the cutover plan)
**Ownership:** Anyone doing infra / DB / release work on this project. Assumes you have DB access and can redeploy the API + Angular app.

---

## What this runbook restores

After running every step below, the platform looks like it did **before** the 4-step `workflows-absorb-automation` track:

- Sidebar shows `Automation → Automations` and `Automation → Workflows` (two entries again).
- `/user/automations/*` routes serve the automation feature module (no redirects).
- Every previously-migrated automation row has `enabled = true` again, `migrated_to_workflow_id` cleared.
- The workflow mirrors (rows with `category = 'Migrated Automation'`) are removed.
- New-org registration installs the 10 preset **automations** (not workflow-mirrors of them).
- Automation dispatcher fires as it did before; workflow engine fires only for genuine multi-step workflows.

## When NOT to use this

- If a **specific** automation needs to fire again but the rest should stay migrated — do the per-row re-enable described in the earlier chat ("How to enable it via db? or via code?") instead. That's surgical; this runbook is nuclear.
- If you only want to **peek** at what the pre-cutover state looked like — spin up a scratch staging DB and downgrade on that, not on production.

## Prerequisites

- Access to run `API\run.cmd upgrade / downgrade` (per `feedback_db_ops_via_docker_helper.md`).
- Access to the deploy pipeline (or manual restart) for both API and Angular app.
- **A fresh DB backup taken right before starting.** The alembic downgrades are tested but this rewrites production data. Take a snapshot.
- Nobody actively editing workflows in the app during the restore window (the workflow mirror rows are about to disappear — an operator mid-edit would see 500s).

Announce a 15-minute maintenance window before starting.

---

## Restore recipe

Do these steps in the exact order below. If any step fails, stop and investigate — do NOT skip ahead.

### 1. Announce + snapshot

```
- Post in #ops: "Reverting workflows-absorb-automation cutover, ~15 min window starting now."
- pg_dump the production DB (via API\run.cmd db-backup or your standard snapshot procedure).
- Note the current Alembic head: run `API\run.cmd alembic current` and record it.
```

### 2. Verify what will change (dry-run inspection)

Run these read-only queries first. Numbers should look sane — if any of them return zero, either the cutover was never done or a previous restore attempt is in flight.

```sql
-- Should equal the total automation count across orgs (should be > 0 if cutover was done)
SELECT COUNT(*) FROM tbl_automations WHERE migrated_to_workflow_id IS NOT NULL;

-- Should equal the same count (one workflow mirror per migrated automation)
SELECT COUNT(*) FROM tbl_workflows WHERE category = 'Migrated Automation';

-- Should be zero — no automation is currently active
SELECT COUNT(*) FROM tbl_automations WHERE enabled = true AND migrated_to_workflow_id IS NOT NULL;

-- Cross-check: every migrated automation's FK still points to a real workflow
SELECT COUNT(*) AS orphans
  FROM tbl_automations a
 WHERE a.migrated_to_workflow_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM tbl_workflows w WHERE w.id = a.migrated_to_workflow_id);
-- Expected: 0. If > 0, some mirrors were deleted manually — the alembic downgrade will still run but restore will be lossy.
```

If any result is unexpected, STOP and investigate before continuing.

### 3. Downgrade the database

Alembic reverses Steps 1 + 2 of this track in order:

```powershell
API\run.cmd downgrade -3
```

The `-3` peels back:
1. `0212_backfill_preset_wf`  — undo Step 2's preset-workflow backfill (removes any preset workflows that were added by the backfill migration)
2. `0211_backfill_autos_to_wf` — for every automation row with `migrated_to_workflow_id` set: delete the mirror workflow + its nodes + trigger; restore `enabled = true`; clear the FK
3. `0210_add_migrated_wf_fk`   — drop the `tbl_automations.migrated_to_workflow_id` column and its index

**Post-downgrade sanity checks:**

```sql
-- Column should be gone
\d tbl_automations
-- ... no migrated_to_workflow_id line in output.

-- Automations should be active again
SELECT COUNT(*) FROM tbl_automations WHERE enabled = true;
-- Expected: same as pre-cutover count.

-- Mirror workflows should be gone
SELECT COUNT(*) FROM tbl_workflows WHERE category = 'Migrated Automation';
-- Expected: 0.
```

### 4. Restore new-org seed behaviour (code revert)

Alembic can't undo the code change in `core/tenants/service.py` (that swap was done in a Git commit, not a migration). You have two options:

**Option A — Git revert the cutover commits (cleanest).** Find the commits that shipped this track:

```powershell
git log --oneline --grep "workflows-absorb-automation"
# or
git log --oneline --grep "absorb automation"
```

Revert them in reverse chronological order:

```powershell
git revert <step-3-commit> <step-2-commit> <step-1-commit> --no-edit
git push origin dev
```

CI runs, deploy the revert to production.

**Option B — Manual code patch (if git-revert is messy).**

- `api/src/app/core/tenants/service.py` — restore the call to `automation.seeds.install_default_org_seeds(session, org_id=org.id)`. Remove the call to `workflows.seeds.install_default_org_workflows(session, org_id=org.id)`.
- `api/src/app/core/workflows/seeds.py` — the 10 preset workflow seed helpers can stay defined (they're idempotent), just aren't called by tenant creation anymore.
- `api/src/app/core/workflows/gallery/preset_automations.py` — either delete or leave; harmless if left.
- `api/src/app/core/automation/seeds.py` — remove the "retained for future re-use, no longer wired at org creation as of 2026-08-04" header comment.

Commit as `revert(workflows-absorb-automation): restore automation seeds on org creation`.

### 5. Restore frontend (sidebar + routes)

Same choice — git revert or manual:

**Option A — Git revert** (same commit set as backend).

**Option B — Manual:**

- `app/src/app/features/user/core/layout/sidebar/*.ts` — re-add the "Automations" entry alongside "Workflows" (name/icon/route match what existed before this track).
- `app/src/app/features/user/user.routes.ts` — remove the four redirect entries; restore the automation feature module route branch (`path: 'automations', loadChildren: () => …`).
- Delete `app/src/app/features/user/core/workflows/redirect-automation.resolver.ts` (no longer used).
- Delete the backend endpoint `GET /api/v1/automations/{id}/migrated-workflow-id` and its service/DAL functions (the FK column doesn't exist anymore, so leaving them causes 500s).

Rebuild + deploy the Angular bundle.

### 6. Restart services

```powershell
API\run.cmd restart
# Then trigger a frontend redeploy per your standard process.
```

### 7. Post-restore verification

**Automations UI:**

```
- Log into Ajay's Workspace (41f9ede9-41b3-44ce-b489-3004566d4068).
- Sidebar shows "Automation → Automations" AND "Automation → Workflows" (two entries under Automation heading).
- Click Automations → list loads with the automations that existed pre-cutover, all `enabled=true`.
- Open any automation → edit page loads (no 404, no redirect).
- Workflows page — should NOT contain rows with category="Migrated Automation" anymore.
```

**Fresh registration:**

```
- Register a burner tenant (qa-restore-verify-YYYYMMDD@example.com).
- New org gets:
    - 10 automations installed (via automation seeds — same as pre-cutover).
    - 5 non-preset workflows installed (Step 20 originals).
- Welcome email arrives within 60s — sent from automation engine (audit trail: tbl_automation_runs).
```

**No-dupes check:**

```
- Fire lead.created for a test lead in Ajay's Workspace.
- Assert: exactly ONE run row. Which table depends on which engine handled it:
    - If workflow "Lead Confirmation" (5-step, seeded by Step 20) exists AND is active → 1 workflow_run.
    - Plus 1 automation_run from the restored "Lead Confirmation" automation.
- Two rows total (one per engine) is EXPECTED after restore — that's the pre-cutover state, where both engines were subscribing but the manager had scoped them to non-overlapping triggers.
- If you see the SAME contact receive the SAME email twice within seconds → an overlap exists; scope one engine to non-overlapping events (manager decision).
```

### 8. Announce

```
- Post in #ops: "workflows-absorb-automation cutover reverted. Automations module is live again. Both engines active."
- Update MEMORY.md project memory (`project_workflows_absorb_automation.md`) with the restore date + reason.
```

---

## If the restore itself fails

**Symptom: alembic downgrade fails partway.**
- Alembic keeps the DB in the version state it reached before the failure. Check `SELECT * FROM alembic_version` to see which revision it stopped at.
- Fix the underlying error, then re-run `API\run.cmd downgrade -3` from wherever it stopped.
- If unrecoverable — restore the pg_dump you took in Step 1, then attempt again.

**Symptom: post-downgrade, Ajay's Workspace shows no automations at all.**
- The downgrade's reverse-mapping logic (delete mirror → restore automation `enabled=true`) may have skipped rows whose FK was cleared manually. Check:
  ```sql
  SELECT COUNT(*) FROM tbl_automations WHERE enabled = true;
  ```
  If low, run:
  ```sql
  -- One-shot fix — restore all disabled automations that had been migrated
  -- (safe only immediately after a downgrade)
  UPDATE tbl_automations SET enabled = true
   WHERE enabled = false;
  ```
  Cross-reference against the pg_dump before running.

**Symptom: sidebar entry doesn't come back after deploy.**
- Angular bundle didn't rebuild. Check the deploy pipeline. Clear browser cache. Confirm you actually shipped the reverted `sidebar/*.ts` and `user.routes.ts`.

**Symptom: duplicate sends observed after restore.**
- Expected only if the manager originally had both engines subscribed to overlapping events. If new overlaps appeared during the migration/restore, disable the workflow "Lead Confirmation" mirror (or whichever event is doubled) via the workflows UI:
  ```
  /user/workflows → find the overlapping workflow → toggle to Draft.
  ```

---

## Related docs

- [README.md](README.md) — the cutover plan this doc reverses.
- [step-1-data-migration-automations-to-workflows.md](step-1-data-migration-automations-to-workflows.md) — the migration that this downgrade reverses.
- [step-4-smoke-verification.md](step-4-smoke-verification.md) — the smoke checklist that gets you TO the cutover state (mirror of this doc, roughly).
- `feedback_execute_migrations_inline.md` (memory) — how to run Alembic in this project.
- `feedback_db_ops_via_docker_helper.md` (memory) — why `run.cmd` and not host-side `psql`.

## Change log

| Date | Change | By |
|---|---|---|
| 2026-08-04 | Runbook drafted alongside cutover plan | Claude Code |
| — | — | — |
