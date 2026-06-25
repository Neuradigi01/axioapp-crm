# DAL Backfill — Align every backend module to Router → Service → DAL

Manager-locked architecture spec (2026-06-25). Every backend module follows the same five-file domain-driven layout:

```
<module>/
├── __init__.py
├── models.py          ← SQLAlchemy ORM only
├── schemas.py         ← Pydantic request/response
├── router.py          ← HTTP only — calls service
├── service.py         ← Business logic + ONLY layer that commits
└── data_access.py     ← Pure CRUD — no transactions
```

This track migrates the existing codebase to that layout, module-by-module, without changing behaviour. **No new features, no refactors, no abstractions.** Pure relocation of SQL/ORM into `data_access.py` and pure relocation of transaction control into `service.py`.

## Why this track exists

Audit on 2026-06-25 found three classes of drift from the locked architecture:

1. **Router-layer transaction violations** (3 modules) — routers calling `db.commit / refresh / rollback` directly. Worst offender: `packs/furniture/modules/inventory/router.py` which orchestrates the whole inventory-create transaction inline.
2. **Folder-form DAL** (8 modules) — older `data_access/` folder convention (2026-06-23) now superseded by the file form. These need flattening.
3. **No DAL at all** (28 modules) — most modules query straight from `service.py`. No layer boundary.

Plus a CI guard (pin-test) at the end so this drift can't recur silently.

## Scope

**In scope:** 39 backend modules — 37 core + 2 pack — that currently have real DB code.

**Out of scope (skipped, with reasons):**
- Empty stubs (`core/files`, `core/ai`, packs `marketplace` / `qr_marketing` / `virtual_staging`, packs `billing`) — these are built in their assigned phases per the master plan. When built, they ship in-spec from day one.
- Read-only / no-models modules (`core/health`, `core/dashboard`, `core/reporting`) — nothing to relocate.

## Track-wide conventions

- **Single-file DAL.** Always `data_access.py` (not folder). Supersedes 2026-06-23 folder rule.
- **Function-per-operation.** `get_X_by_id`, `list_X`, `insert_X`, `update_X`, `delete_X`. Each function does one DB op and returns the result.
- **DAL never imports `service.py` or `router.py`.** It may import models from anywhere (own + cross-module).
- **Service layer owns ALL of:** `db.commit() / db.rollback() / db.flush() / db.refresh()`.
- **Cross-module reads still go through a service**, never directly into another module's DAL. (Routing through service preserves permission/ownership checks the other module may apply.)
- **No behaviour changes.** If a module's tests pass before a step, they must pass after. No bonus refactors.
- **Existing helper service files** (`contacts.consent_service`, `embed.config_service`, etc.) are folded into the main `service.py` only if trivial. Otherwise they stay where they are — same-module service file count is fine; what matters is no SQL/ORM in router and no commit/refresh outside service.

## Theme groupings

| Theme | Steps | Why grouped |
|---|---|---|
| Fix existing rule violations | 1 | Three offenders surfaced by the 2026-06-25 audit; bounded scope |
| Folder → file migration | 2-3 | Modules that already follow the architecture spec; just relocating their DAL form |
| Core backfill | 4-12 | Modules with no DAL today, 3 modules per step (< 10 files / < 400 lines guideline) |
| Pack backfill | 13 | The two real pack modules (custom_orders, field_ops); inventory is fixed in step 1 |
| CI guard + final audit | 14 | Pin-test + walk every module once more to confirm |

## Steps index

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Fix router transaction violations — inventory, leads, dev](step-1-fix-router-transaction-violations.md) | **COMPLETED** | ~0.5 days |
| 2 | [Flatten DAL folder → file — auth, campaigns, contacts, email_sequences](step-2-flatten-dal-folder-batch-1.md) | **COMPLETED** | ~0.5 days |
| 3 | [Flatten DAL folder → file — templates, tenants, users, integrations/whatsapp](step-3-flatten-dal-folder-batch-2.md) | **Pending** | ~0.5 days |
| 4 | [Backfill DAL — activities, appointments, audit](step-4-backfill-activities-appointments-audit.md) | **Pending** | ~0.5 days |
| 5 | [Backfill DAL — billing, calls, catalog](step-5-backfill-billing-calls-catalog.md) | **Pending** | ~0.5 days |
| 6 | [Backfill DAL — conversations, custom_fields, email](step-6-backfill-conversations-custom-fields-email.md) | **Pending** | ~0.75 days |
| 7 | [Backfill DAL — embed, integrations, invitations](step-7-backfill-embed-integrations-invitations.md) | **Pending** | ~0.5 days |
| 8 | [Backfill DAL — leads, notifications, packs](step-8-backfill-leads-notifications-packs.md) | **Pending** | ~0.75 days |
| 9 | [Backfill DAL — permissions, pipelines, reviews](step-9-backfill-permissions-pipelines-reviews.md) | **Pending** | ~0.5 days |
| 10 | [Backfill DAL — saved_views, settings, staff](step-10-backfill-saved-views-settings-staff.md) | **Pending** | ~0.5 days |
| 11 | [Backfill DAL — staff_portal, standard_fields, subscriptions](step-11-backfill-staff-portal-standard-fields-subscriptions.md) | **Pending** | ~0.5 days |
| 12 | [Backfill DAL — tasks, walk_ins](step-12-backfill-tasks-walkins.md) | **Pending** | ~0.5 days |
| 13 | [Backfill DAL — packs/custom_orders, packs/field_ops](step-13-backfill-pack-modules.md) | **Pending** | ~0.5 days |
| 14 | [CI guard pin-test + final audit](step-14-ci-guard-and-final-audit.md) | **Pending** | ~0.5 days |

**Total: 14 steps, ~7 days.**

## Per-step contract

Every step in this track:

1. Touches the 1-3 modules listed in its title.
2. Creates/updates `data_access.py` for each module — function names mirror the existing SQL/ORM calls in `service.py`.
3. Moves SQL/ORM calls out of `service.py` (and out of `router.py` for step 1).
4. Moves `db.commit / rollback / refresh / flush` into `service.py` if any leaked out.
5. Updates imports throughout the module.
6. Runs the module's existing tests; no behaviour changes.
7. Reports stop-and-summary; awaits "proceed."

## Verification (every step)

- Module imports cleanly (`uv run python -c "from src.app.core.<module> import service, router, data_access"`).
- App boots (`uv run uvicorn src.app.main:app --reload` — no import errors).
- Module-specific pytest passes if tests exist.
- Manual smoke against Ajay's Workspace (org `41f9ede9-41b3-44ce-b489-3004566d4068`) — one read + one write endpoint per module per step.
- Grep proves no `db.commit / db.rollback / db.refresh / db.flush` appears in `router.py` or `data_access.py`.

## After this track closes

- The CI pin-test (step 14) prevents recurrence.
- New modules built in later phases (`core/files`, `core/ai`, packs `marketplace` / `qr_marketing` / `virtual_staging` / `billing`) ship in-spec from day one — they're already covered by CLAUDE.md and the master prompt.
- `core/dashboard` and `core/reporting` (read-only, no models) remain as-is; if they ever grow a write path, a future step adds a DAL for them.
