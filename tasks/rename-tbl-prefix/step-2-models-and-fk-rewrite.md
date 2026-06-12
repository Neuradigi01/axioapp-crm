# Step 2 — Models + FK + relationship-string rewrite (Python source)

**Goal:** Walk the naming map from Step 1 and rewrite **every** `__tablename__` string and **every** `ForeignKey("<old_name>.<col>")` string in `api/src/app/` to the new `tbl_*` names. No DB change yet — this step only touches Python source. The application will not boot against the unmigrated DB after this step; that's expected and resolved when Step 3 runs.
**Track:** Rename to `tbl_` Prefix
**Status:** Pending
**Depends on:** Step 1 — naming map approved (user replied "proceed with A" or "B").

---

## Scope

In-scope:

- Update `__tablename__ = "<old>"` → `__tablename__ = "<new>"` in every model file under `api/src/app/core/*/models.py` and `api/src/app/packs/furniture/*/models.py` for the rows marked "needs rename" in the naming map.
- Update every `ForeignKey("<old>.<col>")` string at any nesting depth (Mapped column declarations, `mapped_column(ForeignKey(...))`, `Column(ForeignKey(...))`, composite FKs, `ForeignKeyConstraint([...], ["<old>.id"])`).
- Update any `relationship(secondary="<old>")` string. (SQLAlchemy mapper string references for `back_populates`, `relationship("ClassName")` — confirmed by Step 1 — point at **class names**, not table names, so they need no change. Re-verify if Step 1's grep showed otherwise.)
- Update any string-keyed `Table(...)` or `Index(...)` declarations referencing a table name.
- Re-verify the same in `api/tests/conftest.py` and `api/tests/factories/*` for fixture wiring that uses literal table strings.

Out of scope:

- **No DB change.** No Alembic migration written here.
- **No `text(…)` SQL strings.** Those are Step 4.
- **No seed scripts.** Those are Step 4.
- **No RLS policies.** Those are Step 3.
- **No legacy package** (`api/src/models/*`). Those are already `tbl_*` per Step 1's audit.
- **No frontend.** Step 5 verifies.

## Files to touch

Driven by Step 1's inventory. Expected:

| Area | Approx files |
|---|---|
| `api/src/app/core/<module>/models.py` (× many) | ~25–30 model files |
| `api/src/app/core/<module>/<sub>/models.py` (sub-modules: `contacts/groups`, `contacts/imports`, `leads/imports`, `email/tracking`, `integrations/meta`, `integrations/whatsapp`) | ~6 sub-module model files |
| `api/src/app/packs/furniture/modules/*/models.py` | ~3 pack model files (each contains multiple `__tablename__`) |
| `api/tests/conftest.py` + `api/tests/factories/*` | ~3–6 fixture files, if any literal table strings exist |

**~35–45 modified files.** Above rule 8's per-step file budget on purpose — see README rationale.

## Plan

1. **Re-read `tasks/rename-tbl-prefix/naming-map.md`.** The map is the only source of truth for old → new. Do not invent renames during Step 2.
2. **Single-file pass per model.** For each model file in the naming map's "needs rename" set:
   - Update every `__tablename__ = "<old>"` to the new name.
   - Update every `ForeignKey("<old>.<col>")` to use the new target name.
   - Update every `ForeignKeyConstraint([...], ["<old>.<col>"], ...)` analogously.
   - Update any `Index("<...>", "...", _table_name="<old>")` if such a kwarg pattern is used (rare; check Step 1's pass to confirm).
   - Re-run the file's imports and `Mapped[…]` shapes mentally — but **do not edit non-string code**.
3. **Cross-file FK pass.** Some models reference FKs to tables defined in *other* modules (e.g. `contacts.imports.contact_imports.contact_id → contacts.id`). Use the FK reference map from Step 1 to verify every cross-module FK is updated.
4. **Test factory pass.** If any test factory or fixture has a hardcoded table name (raw inserts, ad-hoc `Table(...)` calls), update it too. The naming map flags these.
5. **Run a final `Grep`** for each of the old plain names across `api/src/app/` (excluding `alembic/versions/`). Expected hits: **0**. Any remaining hit is either a missed string or a `text(…)` call deliberately deferred to Step 4 — flag those in the report.
6. **Do not run pytest.** It will fail because the DB hasn't been migrated yet. The report says so explicitly.

## DB changes / migrations

**None.** This step touches Python source only.

The application will fail to boot against the un-migrated DB after this step. **That is expected.** Step 3's migration repairs the disconnect. Until Step 3 lands, **do not** try to start the API server or run pytest against the live DB.

## Tests

No new tests in this step. Step 5 adds the pin-test that asserts every model's `__tablename__` starts with `tbl_`.

## Smoke

```powershell
# Confirm 0 plain-name __tablename__ entries remain in app/core/* and app/packs/*
Select-String -Path "API\src\app\core\**\*.py" -Pattern '__tablename__\s*=\s*"(?!tbl_)' -AllMatches
Select-String -Path "API\src\app\packs\**\*.py" -Pattern '__tablename__\s*=\s*"(?!tbl_)' -AllMatches
```

Expected output: **empty.** (If option A was picked in Step 1, the pack pattern is `tbl_fp_*` — both grep above and below should be empty. If option B was picked, the second grep should match the `fp_*` pack files only.)

```powershell
# Confirm no ForeignKey references the old names. Replace <old> with each plain name from naming-map.
Select-String -Path "API\src\app\**\*.py" -Pattern 'ForeignKey\("(contacts|leads|audit_logs|appointments|...)\.'
```

Expected output: **empty.**

```powershell
# Sanity: Python compile pass — catches typos in the rewrites
uv --directory API run python -c "import compileall; compileall.compile_dir('src/app', quiet=1)"
```

Expected output: no compile errors.

## Risks

- **Missed FK string.** A `ForeignKey("contacts.id")` left behind will throw `NoReferencedTableError` at app startup *after* Step 3. The Step-2 grep above closes this; Step 3's smoke catches what slips.
- **String-keyed composite FK** (`ForeignKeyConstraint([col1, col2], ["old.col1", "old.col2"])`). Grep for `ForeignKeyConstraint\(` separately to ensure these are updated; Step 1's inventory pass B should have flagged them.
- **Test factories that bypass the ORM.** Any raw `INSERT INTO contacts …` in a fixture will silently fail at Step 5's pytest. Step 4 includes a sweep, but Step 2 should also patch any that Step 1 already flagged.
- **Trailing comma / dict key** style misses. Use a Python compile pass (smoke above) as a paranoia check — won't catch logic errors but will catch syntax breaks from a bad Edit.

## Self-check (10 rules)

- [ ] Rule 1: `core/` did not gain a `packs/` import.
- [ ] Rule 2: No `org_id` columns added or removed; no RLS change.
- [ ] Rule 3: `custom_data` JSONB columns unaffected.
- [ ] Rule 4: Dynamic-form contract unchanged.
- [ ] Rule 5: Sidebar registry untouched.
- [ ] Rule 6: Permissions registry untouched.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: File count is above guidance, on purpose — single coordinated rewrite. README documents this exception.
- [ ] Rule 9: Stop after rewrite + report.
- [ ] Rule 10: No TODOs left behind. No commented-out old `__tablename__` lines. No "we'll catch the rest in Step 3" — Step 2 finishes the source rewrite cleanly.

## Stop & report

```
Step 2 — Rename to tbl_ prefix: Models + FK rewrite

Files changed:
- <list every modified file>

What you can verify:
- `Select-String -Path "API\src\app\core\**\*.py" -Pattern '__tablename__\s*=\s*"(?!tbl_)'` returns empty.
- `Select-String -Path "API\src\app\**\*.py" -Pattern 'ForeignKey\("(old1|old2|...).'` returns empty.
- `uv --directory API run python -c "import compileall; compileall.compile_dir('src/app', quiet=1)"` is clean.
- The app will NOT boot against the current DB until Step 3 lands. This is expected.

Tests added: none — Step 5 lands the pin-test.

Self-check: 10 rules, all green.

Awaiting your "proceed" before Step 3.
```
