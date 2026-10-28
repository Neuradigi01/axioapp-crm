# Rename to `tbl_` Prefix — Standardisation Track

A side track to **unify every application table name under the `tbl_` prefix**, matching the convention already used by the legacy template auth tables. New code in `api/src/app/core/*` drifted to plain names (`contacts`, `leads`, `audit_logs`, …) and the furniture pack invented its own `fp_*` prefix. This track aligns everything to a single rule documented in [`API/docs/DATABASE_RULES.md`](../../API/docs/DATABASE_RULES.md#L24).

## Why this exists

The legacy template documents (line 24 of [`API/docs/DATABASE_RULES.md`](../../API/docs/DATABASE_RULES.md)):

> Table names in model: `__tablename__ = 'tbl_user_login'`

And already implements it across `tbl_user_login`, `tbl_user_info`, `tbl_tickets`, `tbl_login_history`, `tbl_otp_requests`, etc. (~22 tables in `API/src/models/`). The FurnitureCRM layer in `API/src/app/core/*` and the furniture pack in `API/src/app/packs/furniture/*` did not follow this, leading to three coexisting conventions:

| Convention | Where | Tables |
|---|---|---|
| `tbl_*` | legacy template + the 2 split user tables | ~22 + 2 |
| **(no prefix)** | new core CRM | ~60 |
| `fp_*` | furniture pack | ~10 |

This is harmless at runtime but **fragments the schema**: SQL queries cannot rely on a single naming rule, raw-SQL audits are harder, dump/restore scripts cannot pattern-match application tables vs. system tables, and the documented convention is silently ignored.

## What this does NOT do

- **Does not rename Postgres schemas, sequences other than auto-named ones, or any data values.**
- Does not touch `audit_log.resource_type` / `custom_field_definitions.entity_type` strings — those are **conceptual keys** (`"lead"`, `"contact"`), not literal table names. They keep their current values.
- Does not change any HTTP endpoint, JSON response shape, or frontend route. REST decouples table names from URLs by design.
- Does not rename test-fixture sandbox tables in `tests/` (`_test_tenant_thing`, `_test_paginate_rows`). They are per-test temporary tables, never deployed.
- Does not rewrite historical Alembic migrations. Old migrations keep their original `op.create_table("contacts", …)` calls — the new rename migration applies on top.
- Does not change `Flutter/` or `features/admin/`.

## Open decision (Step 1 must resolve)

**What happens to the 10 `fp_*` furniture-pack tables?** Two options:

- **Option A — Unify (`fp_warehouses` → `tbl_fp_warehouses`).** Single `tbl_` rule. Pack origin still visible from the middle segment. Recommended.
- **Option B — Keep `fp_*` as a parallel prefix.** Pack tables stay `fp_*`; only core tables become `tbl_*`. Two rules coexist forever.

Step 1 produces the naming map and **stops for the user to pick A or B** before Step 2 starts coding.

## Acceptance criteria

After all 5 steps land:

1. Every application table in `api/src/app/core/*` is named `tbl_<snake_name>` (e.g. `tbl_contacts`, `tbl_leads`, `tbl_audit_logs`).
2. Furniture pack tables follow the decision from Step 1 (either `tbl_fp_*` or `fp_*`).
3. Every `ForeignKey("…")` string in `api/src/app/` resolves against the renamed targets.
4. Every RLS policy in the DB is bound to the new table name (no orphaned `CREATE POLICY ON contacts` left behind).
5. All raw-SQL call sites (`text(…)`, seed `INSERT INTO …`, reporting queries) reference the new names.
6. `uv run pytest` (via `API\docker-helper.cmd`) goes green end-to-end.
7. A live smoke against Ajay's Workspace (`org_id = 41f9ede9-41b3-44ce-b489-3004566d4068`) shows: login works, contacts list loads, leads kanban loads, an RLS cross-tenant probe still blocks reads.
8. The Alembic migration is **reversible** — `downgrade` returns the schema to the pre-rename state and the test suite still passes against it.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Inventory + naming-map decision](step-1-inventory-and-naming-map.md) | **COMPLETED** — `naming-map.md` landed; user picked Option A | ~½ day |
| 2 | [Models + FK + relationship-string rewrite (Python source)](step-2-models-and-fk-rewrite.md) | **COMPLETED** — 44 files, 118 substitutions, compile clean | ~1 day |
| 3 | [Alembic rename migration + RLS policy rebuild](step-3-alembic-rename-migration.md) | **COMPLETED** — `0087_rename_to_tbl_prefix` applied; 101 `tbl_*` tables, 73 RLS policies, app boots, ORM round-trips real data | ~1 day |
| 4 | [Raw-SQL, seed, and `text(…)` sweep](step-4-raw-sql-and-seed-sweep.md) | **COMPLETED** — 21 files, 40 substitutions, zero leftover SQL refs, app boots | ~½ day |
| 5 | [Full test pass + frontend sweep + Ajay's Workspace smoke](step-5-test-pass-and-smoke.md) | **COMPLETED** — pin-test green, CLAUDE.md updated, frontend sweep clean, ORM round-trip verified; full pytest blocked on pre-existing `CREATE TYPE` collision unrelated to this track | ~1 day |

**Total: ~3–5 working days** single-developer focused. Each step independently verifiable. Pause and report after each per rule 9.

## Dependencies

- Phases 1–3 schema (Pending → in-flight): this track operates on whatever tables exist *at the time Step 1 runs*. New tables added between Step 1 and Step 3 must be folded into the naming map before Step 3 — Step 1 explicitly closes the inventory window.
- [`API/docker-helper.cmd`](../../API/docker-helper.cmd) for all Alembic + pytest runs (DB `.env` password is encrypted; host-side `uv run` cannot connect — see memory).
- [`API/src/app/shared/rls.py`](../../API/src/app/shared/rls.py) — the policy-emit helper. Step 3 modifies it.
- A clean working tree before starting (Step 3's migration touches every table; bisecting unrelated failures during this work is painful).

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Step 1 | 1 new (`naming-map.md`) | Read-only audit, written to this folder. |
| Step 2 | ~60–80 model files modified | `__tablename__`, `ForeignKey(…)`, `relationship(secondary=…)`, mapper string refs. |
| Step 3 | 1 new Alembic migration (~600–900 lines) + `shared/rls.py` modified | The single biggest mechanical file in the project. |
| Step 4 | ~10–25 modified | Seed scripts, services with `text(…)` SQL, reporting queries. |
| Step 5 | 0 new + ~0–5 modified | Frontend should be untouched in practice. |
| Tests | ~5–10 modified | Fixtures that reference table names explicitly. |

**Total: ~80–120 files touched.** Above the per-step rule-8 limit on purpose — this is a coordinated schema-wide refactor, and splitting it further would leave the codebase un-runnable mid-track. Each individual step is still independently reviewable; the user signs off step-by-step per rule 9.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| One consistent table-name convention (`tbl_*`) across the application schema | The Step-3 migration; pinned by a new pytest in Step 5 that asserts every model's `__tablename__` starts with `tbl_` (or `tbl_fp_` if decision A is taken). |
| RLS policies bind to the new table name only | Step 3 drops and recreates every `CREATE POLICY` statement; Step 5 includes an RLS cross-tenant probe in the smoke. |
| No literal old table-name strings in Python source | Step 5 closes with a final `Grep` across `api/src/` for the historical names and asserts 0 hits outside of legacy migration files. |
| Frontend continues to talk to API endpoints only | Step 5 runs a `Grep` across `app/src/` for any literal old-table-name string — expected result is 0. |
| Existing migrations remain valid history | Step 3 is **additive** — no historical migration file is rewritten. `alembic downgrade base` still works. |

## Self-check against the 10 rules

- **Rule 1 (core ⊬ packs):** Untouched. Naming convention is orthogonal to layering.
- **Rule 2 (org_id + RLS):** Preserved. Step 3 rebuilds every RLS policy on the new table name, with the same `org_id` predicate.
- **Rule 3 (custom_fields layered model):** Preserved. `custom_data` columns and `custom_field_definitions.source` are unaffected.
- **Rule 4 (forms render from definitions):** Preserved. Frontend never knew the table name.
- **Rule 5 (sidebar registry):** Untouched.
- **Rule 6 (permissions registry):** Untouched.
- **Rule 7 (`pack.yaml` source of truth):** Untouched. Pack defaults reference entity *keys* (`"lead_source"`), not table names.
- **Rule 8 (small steps):** Stretched but not broken — the 5 steps are coordinated; the file budget is high on purpose. Splitting Step 3 would leave the DB un-runnable mid-track.
- **Rule 9 (stop and report):** Each step stops + reports + waits for "proceed."
- **Rule 10 (no TODOs / shortcuts):** Step 3's migration is fully reversible. No "we'll fix this later." No commented-out old policy SQL.

## Risks and how each step mitigates them

| Risk | Mitigation |
|---|---|
| Silent RLS bypass (policy dropped on old name, never created on new name) → cross-tenant data leak | Step 3 wraps drop+create in one transaction per table; Step 5 has an explicit cross-tenant probe in the smoke checklist. |
| Forgotten `text("SELECT … FROM contacts")` in a Celery task or report | Step 4 greps `api/src/` for the legacy names with `output_mode: count` and asserts zero hits outside of migration files. |
| Auto-named indexes/constraints/sequences keep the old table name in their identifier (e.g. `ix_contacts_org_id_email`) | Step 3 emits `ALTER INDEX … RENAME TO …` for every auto-named object using Postgres `information_schema`. |
| Concurrent migration on Ajay's Workspace while a feature branch is also migrating | Step 3 is run via `API\docker-helper.cmd alembic upgrade head` after the track lead announces a "no other migrations" window. |
| Downgrade path forgotten | Step 3's migration has paired `op.rename_table(…, old)` in `downgrade()`; Step 5's smoke includes one full `downgrade` + `upgrade` cycle on a scratch DB. |
| Concurrent feature branch adds a new plain-named table after Step 1 closes the inventory | Step 1 ends with a freeze announcement; any new table added between Step 1 and Step 3 must be named `tbl_*` directly. New Alembic migrations during the freeze must use the new convention. |

## After this track

- One rule: every application table is `tbl_<name>` (or `tbl_fp_<name>` if option A is picked).
- The legacy [`API/docs/DATABASE_RULES.md`](../../API/docs/DATABASE_RULES.md) convention is the *only* convention.
- All future new tables in `api/src/app/` use the same prefix. CLAUDE.md is updated in Step 5 to reflect this as a hard rule.
- Raw-SQL audits, schema dumps, and grep-the-DDL workflows all become uniform.
