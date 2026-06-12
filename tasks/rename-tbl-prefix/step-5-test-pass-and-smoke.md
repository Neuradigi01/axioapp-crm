# Step 5 — Full test pass + frontend sweep + Ajay's Workspace smoke

**Goal:** Close out the track. Add a pin-test that asserts every model's `__tablename__` follows the new convention so future tables can't drift back. Run a defensive `Grep` across `app/src/` (frontend) for literal old-table-name strings. Run the full backend test suite. Smoke against Ajay's Workspace end-to-end with an explicit RLS cross-tenant probe. Update `CLAUDE.md` so the `tbl_*` convention becomes a stated project rule. Flip every step in this track and parent README to `Done`.
**Track:** Rename to `tbl_` Prefix
**Status:** Pending
**Depends on:** Steps 2–4 — source rewritten, migration applied, raw-SQL swept.

---

## Scope

In-scope:

- New pytest `api/tests/test_table_name_convention.py` — pin-test, see "Tests" below.
- Frontend sweep — `Grep` across `app/src/` for any literal old-table-name strings. Expected count: 0. Update any genuine hit (rare; would be a developer's debug log or a comment).
- Update `CLAUDE.md` — add a line under "10 non-negotiable rules" or in a new "Conventions" section that codifies `tbl_*` as the application-table convention. (The legacy `DATABASE_RULES.md` documents the same thing; CLAUDE.md should mirror it so AI agents don't drift again.)
- Full pytest run via `API\docker-helper.cmd pytest` against the migrated DB. Green end-to-end.
- Smoke against Ajay's Workspace (`org_id = 41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com`):
  1. Owner logs in.
  2. Contacts list loads with at least one row.
  3. Leads kanban loads.
  4. One audit-log entry was written for the login.
  5. RLS cross-tenant probe (psql in container): set `app.current_org_id` to a different org's UUID; `SELECT count(*) FROM tbl_contacts` returns 0 rows that belong to Ajay's org.
- Mark each step file in `tasks/rename-tbl-prefix/` `Status: COMPLETED` and update the README's step table per the [mark-step-status memory](C:\Users\pc\.claude\projects\c--Users-pc-Desktop-Project-CRM-PROJECT-Crm\memory\feedback_mark_step_status_completed.md).
- Add the track to the main `tasks/README.md` "All-steps quick index" as a side track with all 5 steps marked Done.

Out of scope:

- No new features.
- No new tables.
- No model refactors.
- No frontend visual changes.

## Files to touch

| File | Action |
|---|---|
| `api/tests/test_table_name_convention.py` | created — the pin-test. |
| `CLAUDE.md` | modified — add the `tbl_*` convention as a stated rule. |
| `tasks/rename-tbl-prefix/step-1-...md` through `step-5-...md` | modified — flip Status to COMPLETED. |
| `tasks/rename-tbl-prefix/README.md` | modified — flip the step table to Done. |
| `tasks/README.md` | modified — already lists the side track (added in this folder's creation); flip its row to Done. |

Plus any frontend file the sweep flags (expected: 0). Document any found.

**~6 modified + 1 new file.** Within rule-8 budget.

## Plan

1. **Write the pin-test.**
   ```python
   # api/tests/test_table_name_convention.py
   import importlib, pkgutil
   from src.app.shared.orm import Base

   def test_every_app_table_uses_tbl_prefix():
       # Import every model module under src/app so the Base.metadata picks them up.
       import src.app as app_pkg
       for finder, name, ispkg in pkgutil.walk_packages(app_pkg.__path__, prefix="src.app."):
           if name.endswith(".models") or name.endswith("_models"):
               importlib.import_module(name)
       offenders = [
           t.name for t in Base.metadata.tables.values()
           if not t.name.startswith("tbl_") and not t.name.startswith("_test_")
       ]
       assert offenders == [], f"Tables without tbl_ prefix: {offenders}"
   ```
   The `_test_` exception covers the pytest sandbox tables documented in Step 1.
2. **Run the frontend sweep:**
   ```powershell
   $names = @('contacts','leads','audit_logs','appointments','invoices','calls','conversations','organizations','roles','permissions','reviews','tasks','notifications','campaigns','messages','pipelines','staff_profiles','attendance','subscriptions','invitations','email_templates')
   foreach ($n in $names) {
     $hits = Select-String -Path "APP\src\**\*.ts" -Pattern "['\""\``]$n['\""\``]" -AllMatches
     if ($hits) { Write-Host "Frontend hit for [$n]:"; $hits | Format-Table Path, Line }
   }
   ```
   Expected: silent. Triage any hit (likely a debug log, comment, or string constant key — usually not a real reference). Update or document as a conceptual key (same exclusion rule as Step 4).
3. **Update `CLAUDE.md`.** Add a one-line bullet under the "10 non-negotiable rules" — actually, slot it as a new entry under "Locked stack" or "Conventions":
   > **Database table naming:** Every application table in `api/src/app/` is named `tbl_<snake_name>`. Furniture-pack tables follow the option-A/B decision recorded in `tasks/rename-tbl-prefix/naming-map.md`. New tables added going forward use this convention from the first commit; no plain-named tables ever land again.
4. **Run full pytest** via the docker helper. Per the [pause-before-pytest memory](C:\Users\pc\.claude\projects\c--Users-pc-Desktop-Project-CRM-PROJECT-Crm\memory\feedback_pause_before_pytest.md), batch all code work first, then **stop and ask the user before kicking off pytest** because each run takes ~12 minutes.
5. **Run the Ajay's Workspace smoke.** Inside the container's psql:
   ```sql
   -- Confirm Ajay's org has data on the new tables.
   SELECT count(*) FROM tbl_contacts WHERE org_id = '41f9ede9-41b3-44ce-b489-3004566d4068';
   -- Cross-tenant probe.
   SET app.current_org_id = '00000000-0000-0000-0000-000000000000';
   SELECT count(*) FROM tbl_contacts;  -- expected 0
   RESET ALL;
   ```
   Then browser-side: log in as `ajaygogane224@gmail.com`, open the Contacts list, the Leads kanban, and one record's audit-log tab. Confirm everything renders.
6. **Flip statuses.** Update every step file's `**Status:**` line in this folder; update the step table in the folder README; update the row in the main `tasks/README.md`.

## DB changes / migrations

**None.** Step 3 owns the schema change.

## Tests

`api/tests/test_table_name_convention.py` — described above. One test, pinning the new convention forever.

## Smoke

```powershell
# 1. Pin-test alone (fast).
API\docker-helper.cmd pytest tests/test_table_name_convention.py -v

# 2. Full suite (slow — ~12 min; ask before running per memory).
API\docker-helper.cmd pytest

# 3. Frontend sweep.
<run the loop in the Plan step above>

# 4. Ajay's Workspace browser smoke.
# Open the IDE Simple Browser to https://<local-host>/user/dashboard
# Log in as ajaygogane224@gmail.com.
# Click Contacts → list loads.
# Click Leads → kanban loads.
# Open one lead → audit-log tab shows the login event.
```

## Risks

- **A late-arriving model file added during the freeze window is missed.** The pin-test catches this. If it fires, the offending model file is named in the error — fix and re-run.
- **Frontend sweep false positive.** A debug log like `console.log('Saving contacts...')` will hit but is harmless. Triage manually; update if it's a comment in a code path, leave if it's a log message string. Conservative bar: leave most hits unless the string is parsed/used as a key elsewhere.
- **Smoke shows Ajay's org has zero rows on a renamed table.** That would mean Step 3's migration dropped data. Impossible if `rename_table` was used correctly (data follows the table), but if it happens, immediate rollback via the migration's `downgrade()` is the path. Confirm row counts before and after.
- **Pytest concurrency.** Per the memory, never run two pytest processes against the shared test DB. Confirm no other pytest run is in flight before kicking this off.

## Self-check (10 rules)

- [ ] Rule 1: No new `core/` → `packs/` imports.
- [ ] Rule 2: RLS unchanged from Step 3's rebuild; cross-tenant probe in the smoke confirms.
- [ ] Rule 3: `custom_data` JSONB columns + `custom_field_definitions.entity_type` values untouched.
- [ ] Rule 4: Dynamic forms render identically; frontend sweep confirms zero literal table references.
- [ ] Rule 5: Sidebar registry untouched.
- [ ] Rule 6: Permissions registry untouched.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: One new test file + one CLAUDE.md edit + status flips. Well under budget.
- [ ] Rule 9: Stop and report after the full test pass + smoke succeed.
- [ ] Rule 10: No TODOs. CLAUDE.md documents the convention permanently so this kind of drift can't recur. Pin-test catches future drift in CI.

## Stop & report

```
Step 5 — Rename to tbl_ prefix: Full test pass + frontend sweep + smoke

Files changed:
- api/tests/test_table_name_convention.py (created)
- CLAUDE.md (modified — tbl_ convention codified)
- tasks/rename-tbl-prefix/step-{1..5}-*.md (Status → COMPLETED)
- tasks/rename-tbl-prefix/README.md (step table → Done)
- tasks/README.md (side-track row → Done)

What you can verify:
- API\docker-helper.cmd pytest — green end-to-end.
- Pin-test asserts every Base.metadata table starts with tbl_ (or _test_).
- Frontend sweep: zero literal old-table-name strings in app/src/.
- Ajay's Workspace browser smoke: contacts list + leads kanban + audit log all render.
- RLS cross-tenant probe: foreign-org GUC returns 0 rows.

Tests added:
- api/tests/test_table_name_convention.py (1 test).

Self-check: 10 rules, all green.

Track closed. No further steps in this folder. The CLAUDE.md addition + pin-test prevent regression.
```
