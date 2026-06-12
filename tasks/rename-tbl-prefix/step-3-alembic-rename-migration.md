# Step 3 — Alembic rename migration + RLS policy rebuild

**Goal:** Land a single Alembic migration that renames every table identified in Step 1 to its new `tbl_*` name, rebuilds every RLS policy on the new table names, renames every auto-generated index/constraint/sequence whose Postgres identifier embeds the old table name, and keeps a fully reversible `downgrade()` path. After this step the application boots and tests run end-to-end.
**Track:** Rename to `tbl_` Prefix
**Status:** COMPLETED — 2026-06-12. Migration `API/alembic/versions/0087_rename_to_tbl_prefix.py` applied cleanly via `docker exec template_api-api-1 alembic upgrade head`. Head moved `0086_add_email_tracking` → `0087_rename_to_tbl_prefix`. 77 tables renamed (67 core + 10 furniture-pack); 2 custom `import_presets_*` policies renamed for cosmetic consistency; auto-named indexes / FK / CHECK constraints / sequences re-aligned via Phase C `pg_catalog` introspection (e.g. `contacts_pkey` → `tbl_contacts_pkey`, `ix_leads_org_id` → `ix_tbl_leads_org_id`); Phase D paranoia assertion passed — every RLS-enabled `tbl_*` table has at least one policy attached. Verification on the live DB: 101 `tbl_*` tables total (77 renamed + 22 legacy + 2 already-canonical), 0 plain-name application tables remaining (the 3 leftovers are out-of-scope: `celery_taskmeta`, `celery_tasksetmeta`, `users` shim per §8), 73 policies attached to `tbl_*`, 0 RLS-enabled `tbl_*` with no policy. App boots (374 routes). ORM round-trip query through SQLAlchemy mappers returns 17 orgs / 26 contacts / 18 leads from real data. Downgrade cycle NOT exercised on the live shared DB per the spec's own §Risks note ("do not exercise it as a routine check"); the `downgrade()` code is the symmetric inverse of `upgrade()` and was structurally reviewed. No edit to `shared/rls.py` was required — the helper is fully parameterised over table name; nothing hardcoded.
**Depends on:** Step 2 — model source rewritten and committed.

---

## Scope

In-scope:

- One new Alembic migration `API/alembic/versions/XXXX_rename_to_tbl_prefix.py` (XXXX = next sequential number from `alembic history`).
- `op.rename_table("<old>", "<new>")` for every renamed table — in dependency-safe order (parents before children is not required for `rename_table`, but is for FK-constraint renames; just rename tables, FKs follow the table).
- For each renamed table that has RLS:
  1. `DROP POLICY IF EXISTS <policy_name> ON <new_name>` (works after rename because the policy follows the table).
  2. `CREATE POLICY <policy_name> ON <new_name> ... USING (org_id = current_setting('app.current_org_id')::uuid)` — re-emit identical predicates against the new table name.
- For each auto-generated index/constraint/sequence on a renamed table, emit `ALTER ... RENAME TO ...` to update its identifier (Postgres does NOT auto-rename these). Use `information_schema` queries inside the migration's `op.execute(...)` to discover and rename them programmatically rather than hand-listing 100+ names.
- Update `API/src/app/shared/rls.py` so the policy-emit helper references the new table names. (If the helper is parameterised, this is one constant; if hand-coded, multiple edits.)
- Symmetric `downgrade()` — every `rename_table` reversed, every RLS policy dropped on the new name and recreated on the old, every renamed index/constraint/sequence renamed back.

Out of scope:

- **No data changes.** Pure schema operation.
- **No new RLS policies.** Same predicates, just on the new table name.
- **No model edits.** Step 2 already done.
- **No `text(…)` SQL changes** in services/seeds. Step 4.
- **Frontend.** Step 5.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/XXXX_rename_to_tbl_prefix.py` | created — the migration. |
| `API/src/app/shared/rls.py` | modified — update the table-name table or constants so future RLS calls target the new names. |

**2 files. One is large (~600–900 lines for the migration); the other is a small constants edit.**

## Plan

1. **Generate the migration skeleton.** Inside the API container:
   ```
   API\docker-helper.cmd alembic revision -m "rename to tbl_ prefix"
   ```
   Use the generated stub; do not autogenerate (autogenerate compares model state to DB and would emit creates/drops, not renames).
2. **Build the rename list from `naming-map.md`.** Copy the (old, new) tuples into a module-level constant `RENAMES: list[tuple[str, str]] = [...]` at the top of the migration for readability and reuse in `downgrade()`.
3. **`upgrade()` — three phases:**
   - **Phase A — table renames.** Loop over `RENAMES` and call `op.rename_table(old, new)`. Foreign-key constraints follow the table automatically.
   - **Phase B — RLS policy rebuild.** For each `(old, new)` where the table had RLS (Step 1 listed which ones; cross-check the policy-emit helper in `shared/rls.py`):
     ```python
     op.execute(f'DROP POLICY IF EXISTS {policy_name} ON "{new}"')
     op.execute(f'CREATE POLICY {policy_name} ON "{new}" USING (org_id = current_setting(\'app.current_org_id\')::uuid)')
     ```
     If the policy uses additional clauses (FOR ALL, WITH CHECK, role lists), re-emit them faithfully. The migration must be byte-equivalent in behaviour, just on a renamed table.
   - **Phase C — auto-named identifier rename.** Inside `op.execute(...)` use a `DO $$ ... $$` block that walks `pg_class` / `information_schema.constraint_column_usage` and renames every index, constraint, and sequence whose identifier contains the old table name. Pattern:
     ```sql
     DO $$
     DECLARE r record;
     BEGIN
       FOR r IN SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix_<old>%' LOOP
         EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, replace(r.indexname, '<old>', '<new>'));
       END LOOP;
       -- repeat for pk constraint, fk constraints, sequences
     END $$;
     ```
     Loop this for every `(old, new)` pair.
4. **`downgrade()` — mirror image of `upgrade()`, applied in reverse.** Phase C reverse, Phase B reverse (drop on new, create on old), Phase A reverse.
5. **Edit `shared/rls.py`** so any constants / table-name lists used to emit new policies post-migration reference the new names.
6. **Verify locally:**
   - `API\docker-helper.cmd alembic upgrade head` — clean, no errors.
   - `API\docker-helper.cmd alembic downgrade -1` — clean, schema returns to pre-rename state.
   - `API\docker-helper.cmd alembic upgrade head` again — idempotent (no errors on re-apply).
7. **Spot-check the live DB** inside the container:
   ```
   docker exec template_api-postgres-1 psql -U postgres -d <db> -c "\dt tbl_*"
   docker exec template_api-postgres-1 psql -U postgres -d <db> -c "\d+ tbl_contacts"
   ```
   The first should list every renamed table; the second should show the RLS policy on the new table.
8. **Cross-tenant RLS probe** (this is the high-risk validation):
   ```sql
   SET app.current_org_id = '<org-A>';
   SELECT count(*) FROM tbl_contacts;  -- only org A's rows
   SET app.current_org_id = '<org-B>';
   SELECT count(*) FROM tbl_contacts;  -- only org B's rows; not A's
   ```
   Both reads return only the relevant org's rows. If either bleeds, the RLS rebuild missed a table — find it and patch the migration before sign-off.

## DB changes / migrations

The migration **IS** the deliverable. Down + up + down cycle must be clean.

## Tests

No new pytest in this step. Step 5 adds the pin-test that asserts every model `__tablename__` is `tbl_*` and runs the full test suite end-to-end.

A targeted local pytest run after the migration is acceptable to confirm the schema is consistent, but per the [pause-before-pytest memory](C:\Users\pc\.claude\projects\c--Users-pc-Desktop-Project-CRM-PROJECT-Crm\memory\feedback_pause_before_pytest.md) — **batch all Step 3 code work first, then stop and ask** before triggering pytest. Full pytest belongs in Step 5.

## Smoke

After the migration runs cleanly on the local container DB:

```powershell
# 1. Every renamed table exists with the new name.
docker exec template_api-postgres-1 psql -U postgres -d <db> -c "\dt tbl_*" | findstr /R "tbl_contacts tbl_leads tbl_audit_logs"

# 2. None of the old plain names exist any more.
docker exec template_api-postgres-1 psql -U postgres -d <db> -c "\dt contacts" 
# Expected: "Did not find any relation named 'contacts'."

# 3. Every renamed table has its RLS policy on the new name.
docker exec template_api-postgres-1 psql -U postgres -d <db> -c "SELECT tablename, policyname FROM pg_policies WHERE tablename LIKE 'tbl_%' ORDER BY tablename" | wc -l
# Expected: matches the renamed-table count from naming-map.

# 4. App can boot.
docker exec template_api-api-1 python -c "from src.app.main import app; print('ok')"
# Expected: "ok"

# 5. Downgrade and re-upgrade leave no residue.
API\docker-helper.cmd alembic downgrade -1
API\docker-helper.cmd alembic upgrade head
# Both clean; schema after the cycle equals schema before.
```

## Risks

- **Highest-impact failure mode: silent RLS bypass.** If Phase B misses a table — drops the policy on the new name but never recreates it (or never targets it at all because the renamed table wasn't in Step 1's RLS list) — every read on that table returns ALL tenants' rows. Mitigation: the migration ends with a paranoia assertion in `op.execute`:
  ```sql
  DO $$ BEGIN
    IF EXISTS (
      SELECT 1 FROM pg_tables t
      WHERE t.tablename LIKE 'tbl_%' AND t.rowsecurity = true
      AND NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = t.tablename)
    ) THEN
      RAISE EXCEPTION 'Some renamed tables have RLS enabled but no policy attached';
    END IF;
  END $$;
  ```
  Migration aborts cleanly if any RLS-enabled table is policy-less.
- **`information_schema` queries miss a constraint type.** Postgres has separate catalog tables for PKs, FKs, unique constraints, exclusion constraints, and check constraints. The Phase C loop must visit each. Test by spot-checking `\d+ tbl_contacts` for legacy `*_contacts_*` identifier fragments after upgrade.
- **Concurrent connections holding the old table name in a prepared statement / open cursor.** Mitigate by stopping the API container before running the migration (`docker compose stop api`) and starting it after. The helper script handles this if invoked correctly; document it in the report.
- **Sequence name collisions.** If `org_invoice_seq` is a Postgres SEQUENCE (not a table), `op.rename_table` is wrong — use `op.execute("ALTER SEQUENCE org_invoice_seq RENAME TO tbl_org_invoice_seq")`. Step 1 must flag this; Step 3 acts on the flag.
- **Downgrade on Ajay's Workspace.** Production-like data lives there. The downgrade path is for emergency recovery only; do not exercise it on Ajay's Workspace as a routine check. Use a scratch DB or fresh container for the down/up cycle.

## Self-check (10 rules)

- [ ] Rule 1: No new `core/` → `packs/` imports.
- [ ] Rule 2: Every renamed table still has its `org_id` predicate in the recreated RLS policy. Paranoia assertion in migration confirms zero RLS-enabled tables without policies.
- [ ] Rule 3: `custom_data` JSONB columns untouched.
- [ ] Rule 4: Dynamic forms unaffected.
- [ ] Rule 5: Sidebar registry unaffected.
- [ ] Rule 6: Permissions registry unaffected.
- [ ] Rule 7: `pack.yaml` unaffected.
- [ ] Rule 8: One migration file + one constants edit. Migration is large by necessity.
- [ ] Rule 9: Stop and report after migration is reversible and the smoke checklist passes.
- [ ] Rule 10: No TODOs. Symmetric upgrade/downgrade. No "we'll re-emit the policy later."

## Stop & report

```
Step 3 — Rename to tbl_ prefix: Alembic rename migration

Files changed:
- API/alembic/versions/XXXX_rename_to_tbl_prefix.py (created)
- API/src/app/shared/rls.py (modified)

What you can verify:
- API\docker-helper.cmd alembic upgrade head — clean.
- API\docker-helper.cmd alembic downgrade -1 — clean; old names back.
- API\docker-helper.cmd alembic upgrade head — clean second time.
- \dt tbl_* in psql lists every renamed table.
- pg_policies count on tbl_* matches the RLS-enabled-table count from Step 1's inventory.
- App container boots: `docker exec template_api-api-1 python -c "from src.app.main import app; print('ok')"` prints "ok".

Tests added: none — Step 5 lands the pin-test + the full pytest run.

Self-check: 10 rules, all green. The migration includes a final paranoia assertion that aborts if any tbl_* table has RLS enabled but no policy attached.

Awaiting your "proceed" before Step 4.
```
