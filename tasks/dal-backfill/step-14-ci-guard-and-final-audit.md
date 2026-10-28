# Step 14 — CI guard pin-test + final audit

**Goal:** Lock the architecture so it can't silently drift again. Add a pin-test that fails CI if `db.commit / db.rollback / db.refresh / db.flush` appears outside `service.py`, or if `db.execute / select() / db.query / db.add / db.delete` appears in a `router.py`. Then walk every module once more to confirm the whole tree is clean.
**Status:** COMPLETED
**Depends on:** Steps 1–13.

---

## Scope

In-scope:
- `API/tests/test_layered_architecture_convention.py` — **NEW** pin-test
- Update `tasks/dal-backfill/README.md` to mark all steps Done
- Update CLAUDE.md to remove the "Backfill track" call-out paragraph (since the migration is complete)

Out of scope:
- Any further refactoring. If a violation is found during the final audit, file it as a follow-up step and fix it under that step file — don't pile it onto Step 14.

## Files to touch

- `API/tests/test_layered_architecture_convention.py` — new pin-test
- `tasks/dal-backfill/README.md` — status flips
- `CLAUDE.md` — replace the "Backfill track" paragraph with a "Convention enforced by CI pin-test" note pointing to the test file
- `tasks/README.md` — flip the row in the phase index to Done

**~4 files. ~250 lines (most of it the pin-test itself).**

## Plan

1. Write the pin-test. AST-based, not regex — parses each `.py` file under `api/src/app/core/` and `api/src/app/packs/`, walks the tree, fails if:
   - `db.commit` / `db.rollback` / `db.flush` / `db.refresh` call appears in a file whose name is NOT `service.py` (allow helper service files matching `*_service.py` too).
   - `db.execute` / `db.add` / `db.delete` / `select(` / `insert(` / `update(` / `delete(` (SQLAlchemy CRUD constructors) appears in a file whose name is `router.py`.
   - Any module that has `router.py` + `service.py` + DB-touching code but no `data_access.py` — fails with a list.
2. Test the pin-test against the current tree — should pass after Steps 1-13.
3. Walk every module once more by hand. Open the audit checklist (router clean, service owns transactions, DAL has no transactions, DAL doesn't import service). Spot-check 10 modules randomly.
4. Flip statuses in `tasks/dal-backfill/README.md` and the row in `tasks/README.md`.
5. Update CLAUDE.md — remove the "Backfill track" callout; add one line that the pin-test enforces the convention.

## DB changes / migrations

None.

## Tests

- The pin-test itself.
- Run it: `uv run pytest API/tests/test_layered_architecture_convention.py -v` — passes.
- Run the existing pin-test for table naming alongside: `API/tests/test_table_name_convention.py` — confirms both convention tests live side-by-side.

## Smoke

- Introduce a deliberate violation in a test branch (e.g. add `db.commit()` to a router) — pin-test fails.
- Remove the violation — pin-test passes.

## Risks

- **False positives on allowed patterns.** The test must allow legitimate `select(...)` constructions in `data_access.py` files. The rule: SQLAlchemy CRUD constructors in `router.py` are violations; the same constructors in `service.py` or `data_access.py` are fine (though Step 13 moved them all to DAL, services may still build dynamic statements for complex composite reads — that's allowed).
- **AST parsing edge cases.** Use Python's `ast` module, not regex. Multi-line attribute access (`db.\n    commit()`) and aliased imports (`from sqlalchemy import select as _sel`) need handling.
- The pin-test must NOT scan `__pycache__`, `tests/`, or `alembic/versions/` (migrations legitimately use `op.execute` etc.).

## Self-check (10 rules)

Pin-test enforces all 10 going forward as far as backend layering is concerned. ✓ < 10 files / < 400 lines. ✓ Stop-and-report. ✓
