# Step 1 — Inventory + naming-map decision

**Goal:** Produce a single, committed `naming-map.md` document under `tasks/rename-tbl-prefix/` listing **every** application table in the repo, its current name, its proposed new name, and the impact surface (FK references, RLS policies, raw-SQL call sites). Surface the one open decision — what to do with the 10 `fp_*` furniture-pack tables — and **stop for the user to pick option A or B** before any code change.
**Track:** Rename to `tbl_` Prefix
**Status:** Pending
**Depends on:** None. This step is purely read-only auditing.

---

## Scope

In-scope:

- A full grep of every `__tablename__ = "…"` in `api/src/` and a small grep of `__tablename__ = '…'` (mixed quoting in the legacy package). Output: a deduplicated table list.
- A full grep of every `ForeignKey("<name>.<col>")` string under `api/src/app/`. Output: a per-target reference count, so Step 2 knows what to rewrite.
- A grep of every `text("…")` SQL fragment under `api/src/` containing a literal table reference (FROM/JOIN/UPDATE/INSERT INTO/DELETE FROM). Output: a per-file list.
- A grep of every Alembic policy / SQL string under `API/src/app/shared/rls.py` and `API/alembic/versions/` referencing a table name. Output: the RLS-policy impact set for Step 3.
- A grep of every `relationship(secondary="…")` and any `Mapped["…"]` back-reference string under `api/src/app/`. (Mapper strings reference *class names*, not table names — Step 1 confirms this with the grep and documents the result.)
- A grep of every seed-data SQL file (`INSERT INTO …`) under `API/scripts/`, `API/seeds/`, or wherever they live.
- The one **open decision** to surface to the user:
  - **Option A** — unify (`fp_warehouses` → `tbl_fp_warehouses`)
  - **Option B** — keep `fp_*` as a parallel prefix
  - Recommendation: **A**, with reasoning in the doc.

Out of scope:

- No code changes. **Zero edits to source.**
- No DB changes. No migration written.
- No frontend touched.
- No pytest run.

## Files to touch

| File | Action |
|---|---|
| `tasks/rename-tbl-prefix/naming-map.md` | created — the full inventory + decision doc. |

**1 new file. No source changes.**

## Plan

1. **Inventory pass A — every `__tablename__`.** Run `Grep` for `__tablename__\s*=\s*[\"']([a-zA-Z_]+)[\"']` across `api/src/` with `output_mode: content`. Deduplicate. Group by:
   - **Legacy template** (`API/src/models/*`) — already `tbl_*`, **no rename**.
   - **Core CRM** (`api/src/app/core/*`) — split into (a) already `tbl_*` and (b) plain — the plain set is what Step 2 rewrites.
   - **Furniture pack** (`api/src/app/packs/furniture/*`) — `fp_*` — Option A/B decision applies.
   - **Test sandbox** (`api/tests/`) — leave as-is, document why.
2. **Inventory pass B — every `ForeignKey("…")` string.** Run `Grep` for `ForeignKey\([\"']([a-zA-Z_]+)\.` under `api/src/app/`. Build a per-target-table reference count. Verify each FK target appears in pass A's list.
3. **Inventory pass C — `text(…)` SQL.** Run `Grep` for `text\(` under `api/src/` with `output_mode: content`. Manually filter out the ones that don't reference table names (RLS GUC setters like `text("SET app.current_org_id = …")` are unaffected). Record the affected files.
4. **Inventory pass D — RLS policies.** Run `Grep` for `CREATE POLICY|ENABLE ROW LEVEL SECURITY|FORCE ROW LEVEL SECURITY` under `API/`. Two known sites: `API/src/app/shared/rls.py` and the migration `API/alembic/versions/0042_import_presets.py`. Plus any inline policy creation in other migrations — Step 1 finds them all.
5. **Inventory pass E — relationship + mapper strings.** Run `Grep` for `relationship\(\s*[\"']` and `Mapped\[[\"']` under `api/src/app/`. SQLAlchemy mapper strings reference *class names*, not table names — confirm this with the grep and document that **no Step 2 work is needed for mapper strings**.
6. **Inventory pass F — seed SQL.** Run `Grep` for `INSERT INTO\s+[a-zA-Z_]+` under `API/`. Record the affected files.
7. **Build the naming map.** Two-column table: `current_name | proposed_new_name`. Apply rules:
   - `contacts` → `tbl_contacts`
   - `audit_logs` → `tbl_audit_logs`
   - `org_invoice_seq` → `tbl_org_invoice_seq` (verify in code whether this is a table or a Postgres sequence; if sequence, document it stays as-is)
   - Sub-tables keep their full names: `contact_group_members` → `tbl_contact_group_members`, **not** `tbl_contact_groups_members`.
   - `messages` → `tbl_messages` (already unambiguous; conversations.messages is its conversational parent, but the table name stands alone).
   - `fp_*` rows show both A and B in the column.
8. **Surface the open decision.** Bottom of the doc has an explicit "Awaiting decision" section: A vs B, recommendation A, reasoning. **Step 1 stops here.**

## DB changes / migrations

**None.** Pure read-only auditing.

## Tests

**None.** Step 1 produces a doc; nothing executable changes.

## Smoke

After committing `naming-map.md`, the user opens it, picks A or B, and replies "proceed with A" (or "proceed with B"). Step 2 starts only after that reply.

A self-check the user can run to sanity-check the inventory:

```powershell
# Count: should match Step 1's "core CRM, plain name" row count
Select-String -Path "API\src\app\core\**\*.py" -Pattern '__tablename__\s*=\s*"[a-z]'
```

Expected count is documented inline in the naming map. Mismatch = Step 1 missed something; do not proceed.

## Risks

- **Inventory drift between Step 1 and Step 3.** A feature branch could add a new plain-named table after Step 1 closes. Mitigation: Step 1's report ends with a freeze announcement — "no new tables until Step 3 lands; new migrations during this window must use `tbl_*` directly." Track-lead enforces this manually; there is no automated lock.
- **`text("SELECT … FROM contacts")` hidden behind f-strings or string concatenation.** Grep finds literal references, not constructed ones. Step 1 also runs a `Grep` for the bare strings `'contacts'`, `'leads'`, `'audit_logs'` across `api/src/` as a paranoia check, and notes any suspicious hits for manual review in Step 4.
- **Sequences (e.g. `org_invoice_seq`) confused with tables.** Step 1 verifies via the model file whether each `__tablename__` is a real table or a sequence object. Sequences are renamed in the same migration (Step 3) but via `ALTER SEQUENCE`, not `RENAME TABLE`.
- **Test-sandbox tables (`_test_tenant_thing`, `_test_paginate_rows`)**: documented as **excluded** — they are created at test setup and dropped at teardown, never live in prod.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` → `packs/` import added (no code added).
- [ ] Rule 2: No new tables; org_id + RLS unaffected.
- [ ] Rule 3: Custom-fields layered model unaffected.
- [ ] Rule 4: Dynamic forms unaffected.
- [ ] Rule 5: Sidebar registry unaffected.
- [ ] Rule 6: Permission registry unaffected.
- [ ] Rule 7: `pack.yaml` unaffected.
- [ ] Rule 8: Single deliverable (one doc); well under 400 lines / 10 files.
- [ ] Rule 9: Step stops after the doc lands; awaits "proceed with A/B" from the user.
- [ ] Rule 10: No TODOs in the doc; the open decision is surfaced explicitly, not deferred.

## Stop & report

After `naming-map.md` is committed, post the report:

```
Step 1 — Rename to tbl_ prefix: Inventory + naming-map decision

Files changed:
- tasks/rename-tbl-prefix/naming-map.md (created)

What you can verify:
- Open tasks/rename-tbl-prefix/naming-map.md.
- Confirm the table count matches your expectation (~60 plain core tables + ~10 fp_ + ~22 legacy).
- Pick option A (recommended) or option B for fp_* tables.

Tests added: none — Step 1 is documentation only.

Self-check: 10 rules, all green.

Awaiting your "proceed with A" or "proceed with B" before Step 2.
```
