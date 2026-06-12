# Step 4 — Raw-SQL, seed, and `text(…)` sweep

**Goal:** Find and update every remaining literal old-table-name string in `api/src/` outside of model files and historical migrations — `text(…)` SQL in services, raw `INSERT INTO` in seed scripts, reporting queries, Celery tasks, and any utility that bypasses the ORM. Leave conceptual key values (`audit_log.resource_type = "lead"`, `custom_field_definitions.entity_type = "contact"`) **untouched** — those are entity keys, not table names.
**Track:** Rename to `tbl_` Prefix
**Status:** COMPLETED — 2026-06-12. Scanned 409 .py files under `API/src/app/`, modified **21 files** with **40 raw-SQL substitutions** (Python script with SQL-keyword-anchored regex patterns: `FROM/JOIN/UPDATE/INSERT INTO/DELETE FROM/REFERENCES/TRUNCATE` + word boundary). Final cross-check grep returns zero hits. Idempotent — re-running the script reports 0 modifications. App boots cleanly (374 routes). Two docstrings were swept up as a free bonus (`core/staff/service.py` and `packs/furniture/modules/billing/router.py`) — they describe the actual tables now correctly named `tbl_leads` / `tbl_org_settings`, so kept as more-accurate documentation. The `audit_log.resource_type` / `custom_field_definitions.entity_type` conceptual key strings were left untouched per the spec's out-of-scope rules — the SQL-keyword patterns don't match plain quoted string keys. No DB changes (Step 3 owns the schema). No tests added (Step 5 lands the pin-test + full pytest pass).
**Depends on:** Step 3 — migration applied on the dev DB and Ajay's Workspace; app boots.

---

## Scope

In-scope:

- Sweep every `text("…")` and `text('…')` SQL fragment under `api/src/` and update literal `FROM`/`JOIN`/`UPDATE`/`INSERT INTO`/`DELETE FROM` references to the new `tbl_*` names. Step 1's inventory pass C gives the file list.
- Sweep every seed script (`api/scripts/seed*.py`, `api/seeds/*.sql`, or wherever Step 1 located them) for `INSERT INTO <old> ...` and update.
- Sweep every Celery task file under `api/src/app/**/tasks*.py` (and any module-level `tasks.py` files like `core/leads/imports/tasks.py`) for raw SQL.
- Sweep any reporting query module (e.g. `api/src/app/core/reporting/*`) for raw SQL.
- Update any management script under `api/scripts/` that runs raw SQL against the app DB.
- Output: zero hits on a final grep for old plain names across `api/src/` excluding `alembic/versions/`.

Out of scope:

- **`audit_log.resource_type` values.** Conceptual entity keys (`"lead"`, `"contact"`). DO NOT rename to `"tbl_leads"` — that would (a) break the frontend's audit-log viewer if it ever lands, (b) require a data migration on Ajay's Workspace, (c) confuse the semantic distinction between "table" and "entity."
- **`custom_field_definitions.entity_type` values.** Same reasoning.
- **String values stored in `module_registry`, `pack.yaml`, or any other config that keys on entity name.** Those are conceptual.
- **Historical Alembic migrations** (`API/alembic/versions/0001_*` through the last one before Step 3's). They run in historical order; their `create_table("contacts", …)` calls are correct *for the moment they ran*. Step 3 renames the result. Do not edit historical migrations.
- **Legacy `API/src/models/*` and `API/src/routers/*`** — those already use `tbl_*` and operate on the legacy template tables. No changes needed there.
- **Frontend.** Step 5.

## Files to touch

Driven by Step 1's inventory pass C and pass F. Expected:

| Area | Approx files |
|---|---|
| Service-layer `text(…)` SQL — billing, reporting, audit, calls | ~5–10 service files |
| Celery task SQL — bulk import, embed processing, integration retries | ~3–6 task files |
| Reporting / analytics queries | ~2–5 query modules |
| Seed scripts (`api/scripts/seed*`, `api/seeds/*`) | ~3–10 files |
| Management / one-off scripts under `api/scripts/` | variable |

**~10–25 modified files.**

## Plan

1. **Re-read Step 1's pass C and pass F output.** Open every file listed.
2. **Edit each `text("…")` SQL fragment.** Replace every literal `contacts`, `leads`, `audit_logs`, etc. (and the `fp_*` set per Step 1's A/B decision) with the new name. **Do not** edit GUC-setter calls like `text("SET app.current_org_id = …")` — those have no table reference.
3. **Edit seed SQL.** `INSERT INTO contacts ...` → `INSERT INTO tbl_contacts ...`.
4. **Edit Celery task SQL.** Same as service layer.
5. **Edit reporting SQL.** Same.
6. **Run a final `Grep`** across `api/src/` for the bare strings (one per old name) with `output_mode: count`, excluding `alembic/versions/`. Expected: **0** hits per name.
7. **Verify with a paranoia broader grep:**
   ```powershell
   Select-String -Path "API\src\**\*.py" -Pattern "['\""]?(contacts|leads|audit_logs|appointments|invoices|messages|...)['\""]" -AllMatches | Where-Object { $_.Path -notmatch "alembic" } | Where-Object { $_.Line -match 'FROM|JOIN|UPDATE|INSERT|DELETE|TABLE' }
   ```
   Expected: empty. Some false positives may show (`message_id`, `lead_score`, etc.); manually triage.
8. **Sanity boot.** `docker exec template_api-api-1 python -c "from src.app.main import app; print('ok')"` — still prints "ok."
9. **Run a single targeted pytest module** to confirm the rewritten raw-SQL paths still execute — e.g. `pytest tests/core/billing -v` if billing has the most raw SQL. Full pytest is Step 5.

## DB changes / migrations

**None.** Schema is already at the post-rename state from Step 3. Step 4 only updates Python code that talks to it.

## Tests

No new pytest. Step 5 ships the pin-test.

## Smoke

```powershell
# 1. Zero literal old-table-name references in non-migration source code.
foreach ($name in @('contacts','leads','audit_logs','appointments','invoices','messages','calls','conversations','organizations','roles','permissions','reviews','tasks','notifications','campaigns')) {
  $hits = Select-String -Path "API\src\app\**\*.py" -Pattern "[\""']$name[\""']" | Where-Object { $_.Line -match 'FROM|JOIN|UPDATE|INSERT|DELETE|RENAME TABLE' }
  if ($hits) { Write-Host "STILL FOUND: $name" }
}
# Expected: silent (no STILL FOUND lines).

# 2. App still boots.
docker exec template_api-api-1 python -c "from src.app.main import app; print('ok')"

# 3. A single billing test (raw SQL hot spot) passes.
API\docker-helper.cmd pytest tests/core/billing -v
```

## Risks

- **Old name embedded in an f-string** (e.g. `text(f"SELECT * FROM {table_name}")`). The grep finds literal strings, not interpolations. Step 4 must also `Grep` for `f"…{[a-z_]+}…"` patterns in the same files Step 1's pass C flagged. If `table_name` is a variable, trace where it's assigned and update if needed.
- **Old name in a docstring.** Cosmetic. Update if discovered; do not search exhaustively.
- **A reporting query that builds SQL by string concatenation.** Same as the f-string case — trace the construction site.
- **A management script (`api/scripts/*.py`) that nobody has run since DR.7.** May have stale references. Update if Step 1 flagged it; otherwise leave for the eventual run-time failure (acceptable for one-off ops scripts).
- **Step 5's pytest will catch what Step 4 missed.** That is the safety net; do not skip Step 5 even if Step 4's smoke is clean.

## Self-check (10 rules)

- [ ] Rule 1: No new `core/` → `packs/` imports.
- [ ] Rule 2: No RLS changes (Step 3 owns that).
- [ ] Rule 3: `custom_data` columns + `custom_field_definitions.entity_type` values explicitly untouched.
- [ ] Rule 4: Dynamic forms unaffected; entity_type keys preserved.
- [ ] Rule 5: Sidebar registry unaffected.
- [ ] Rule 6: Permissions registry unaffected.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: File list is bounded by Step 1's inventory; review per-file.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. No "I'll update the seed script later." Every literal name is corrected or explicitly excluded with a comment explaining why (conceptual key, not table name).

## Stop & report

```
Step 4 — Rename to tbl_ prefix: Raw SQL + seed sweep

Files changed:
- <list every modified file>

What you can verify:
- The smoke loop above prints no "STILL FOUND" lines.
- App boots: `docker exec template_api-api-1 python -c "from src.app.main import app; print('ok')"` is "ok".
- A targeted pytest run on a raw-SQL heavy module (e.g. billing) passes.

Tests added: none — Step 5 lands the full pytest pass + pin-test.

Self-check: 10 rules, all green.

Awaiting your "proceed" before Step 5.
```
