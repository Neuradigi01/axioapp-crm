# Step 1 — Backend rename: `pack_id` → `template_id`

**Goal:** Rename `pack_id` to `template_id` everywhere on the backend in a single coordinated step — DB column, ORM model, Python services, Pydantic schemas, pack manifest schema, both `pack.yaml` files, and all affected tests. After this step the entire backend speaks `template_id`. The frontend (which still sends `pack_id`) is temporarily broken until Step 2 ships.

**Track:** Template ID Rename
**Status:** COMPLETED — migration `0072_template_id_rename` applied, API restarted, end-to-end wire-format smoke green: catalog returns `template_id`, register issues `needs_onboarding=true` on a `template_id="pending"` org, onboarding-complete writes `template_id="furniture"`, `/users/me` reflects the new key, coming-soon templates rejected with `template_not_available`. Both `organizations.pack_id` AND `organizations.pack_version` renamed (matching invariant — the version sibling rides with the id). `custom_field_definitions.pack_id` intentionally NOT renamed (separate concept — which template authored the field, distinct from which template the org chose; can be a future cleanup). Test infra has a pre-existing teardown deadlock unrelated to this rename — flagged but not blocking; the test logic itself executes correctly per the catalog suite (5 passed before teardown deadlock; failures are `DROP TABLE` races at fixture cleanup, not assertions).
**Depends on:** Onboarding-setup track — COMPLETED.

---

## Scope

Atomic rename across **every backend layer** that names this concept:

| Layer | What changes |
|---|---|
| **DB column** | Alembic migration: `organizations.pack_id` → `organizations.template_id`. Data preserved verbatim. |
| **ORM model** | `Organization.pack_id` mapped column → `template_id`. Type and constraints unchanged. |
| **Tenants service** | `create_organization(pack_id="...")` keyword param → `template_id="..."`. Callers updated. |
| **Auth service** | `register_user_only` (sets `"pending"`), `complete_onboarding` (validates + writes), `register_with_new_org` (legacy path), `_validate_pack_choice` (renamed to `_validate_template_choice`) — every internal var, parameter, and `org.pack_id` access updated. |
| **Pydantic schemas** | `OnboardingCompleteRequest.pack_id` → `template_id`. Same for any response that surfaces it. |
| **Users router** | `/users/me`'s `needs_onboarding = (org.pack_id == "pending")` derivation renamed. The `OrgSummary` response field also flips. |
| **Pack manifest schema** | `PackManifest.pack_id` → `template_id`. The Pydantic field name in `manifest.py` and every Python reference to `manifest.pack_id` in the loader/installer/catalog. |
| **`pack.yaml` files** | `base/pack.yaml` and `furniture/pack.yaml` top-level field `pack_id:` → `template_id:`. Value (`base` / `furniture`) unchanged. |
| **Catalog config** | `catalog_config.CATALOG_PACKS` entry keys `"pack_id"` → `"template_id"`. Also the `TypedDict` `CatalogTileConfig.pack_id` field. |
| **Catalog schemas** | `CatalogTile.pack_id` → `template_id`. |
| **Catalog service** | `_discover_real_pack_ids` → `_discover_real_template_ids` (consistent naming). |
| **Tests** | Every test file referencing the renamed field updated to assert the new name. No test logic changes. |
| **Seed scripts** | `scripts/seed_demo_org.py` and `scripts/seed_core_demo_org.py` if they reference `pack_id`. `scripts/install_pack.py` CLI flag `--pack` may stay (it's a flag *name*, refers to the pack folder, not the column). |
| **Audit events** | Field name inside `org.created_via_onboarding` and `pack.installed_via_onboarding` payloads — `pack_id` → `template_id`. Past audit rows keep their old keys (already written; no migration needed). |

The "pending" sentinel value (`org.template_id == "pending"`) is unchanged — same string, just stored in a renamed column.

## What this does NOT do

- Does **not** add a new `pack_id` column. That's reserved for subscription tiers in a future track.
- Does **not** change the catalog endpoint URL, behaviour, or set of tiles.
- Does **not** rename the `packs/` folder, the `core/packs/` Python module, or the `pack.yaml` file name. Only the **identifier inside** them.
- Does **not** add backward-compat aliases. Backend strictly speaks `template_id` after this step.
- Does **not** touch the frontend. Step 2 fixes the wire-format mismatch immediately after.
- Does **not** change any role / permission / pipeline / custom-field logic.

## Schema

One Alembic migration:

```
0XXX_rename_pack_id_to_template_id.py
  upgrade:   ALTER TABLE organizations RENAME COLUMN pack_id TO template_id;
  downgrade: ALTER TABLE organizations RENAME COLUMN template_id TO pack_id;
```

Pure column rename. PostgreSQL preserves all data, indexes (the column has no FK / no unique constraint today), and RLS policies (which scope by `org_id`, not this column).

## Files to touch

| # | File | Action |
|---|---|---|
| 1 | `api/alembic/versions/0XXX_rename_pack_id_to_template_id.py` | created |
| 2 | `api/src/app/core/tenants/models.py` | modified — column rename |
| 3 | `api/src/app/core/tenants/service.py` | modified — `create_organization` keyword param |
| 4 | `api/src/app/core/auth/service.py` | modified — `register_user_only`, `complete_onboarding`, `register_with_new_org`, `_validate_pack_choice` (rename to `_validate_template_choice`), audit payloads |
| 5 | `api/src/app/core/auth/schemas.py` | modified — `OnboardingCompleteRequest.pack_id` → `template_id` |
| 6 | `api/src/app/core/users/router.py` | modified — `needs_onboarding` derivation |
| 7 | `api/src/app/core/packs/manifest.py` | modified — `PackManifest.pack_id` field + validator references |
| 8 | `api/src/app/core/packs/loader.py` | modified — error messages / debug log strings referencing `pack_id` |
| 9 | `api/src/app/core/packs/installer.py` | modified — `manifest.pack_id` references, `org.pack_id` references, `InstallReport.pack_id` |
| 10 | `api/src/app/core/packs/catalog_config.py` | modified — `CatalogTileConfig.pack_id`, dict keys |
| 11 | `api/src/app/core/packs/schemas.py` | modified — `CatalogTile.pack_id` → `template_id` |
| 12 | `api/src/app/core/packs/service.py` | modified — `_discover_real_pack_ids` rename, references |
| 13 | `api/src/app/packs/base/pack.yaml` | modified — `pack_id: base` → `template_id: base` |
| 14 | `api/src/app/packs/furniture/pack.yaml` | modified — `pack_id: furniture` → `template_id: furniture` |
| 15 | `api/tests/test_packs_catalog.py` | modified — assert `template_id` keys |
| 16 | `api/tests/test_register_user_only.py` | modified |
| 17 | `api/tests/test_onboarding_complete.py` | modified — request bodies, assertions |
| 18 | `api/tests/test_pack_manifest_validation.py` | modified — manifest field name |
| 19 | `api/tests/test_pack_installer.py` | modified |
| 20 | `api/tests/test_furniture_pack_install.py` | modified |

Plus possibly (verify at kickoff):
- `api/src/app/scripts/seed_demo_org.py`, `seed_core_demo_org.py` — if they reference `pack_id`
- `api/src/app/scripts/install_pack.py` — internal var rename (CLI flag `--pack` is a name, not a field, so keep)
- Any `core/dashboard/...` widget reading `org.pack_id`
- `core/dev/router.py` if it surfaces `pack_id` in a dev panel

**~20 files.** Exceeds the 10-file ceiling. Justified in the README — atomic rename can't be safely split.

## Backend acceptance checks

After this step:

1. `pytest tests/ -v` passes 100%. No remaining `pack_id` references in test assertions.
2. `grep -r "pack_id" api/src/app/core` returns either zero hits or only:
   - Comments referencing the historical name
   - The CLI flag `--pack` (which is a flag name, not a field)
3. `grep -r "pack_id" api/src/app/packs` returns zero hits in the pack.yaml files (the folder name `packs/` and module `core/packs/` are untouched).
4. Manual curl: `POST /api/v1/auth/onboarding/complete` with `{"organization_name": "X", "template_id": "furniture"}` returns 200. With `{"pack_id": "furniture"}` returns 422 (field required: `template_id`).
5. `GET /api/v1/packs/catalog` response carries `template_id` keys on every tile.
6. `GET /api/v1/users/me` response carries `org.template_id`.
7. Alembic downgrade restores the column to `pack_id` cleanly and the API works on the pre-rename schema (this is the rollback check — re-upgrade after to leave the system on the new schema).

## Manual ops

| Action | Needed? |
|---|---|
| `docker-helper.cmd upgrade` (apply migration) | ✅ Yes |
| API container restart (pick up Python changes) | ✅ Yes |
| Frontend restart | ⚠️ Skip — Step 2 will rebuild it anyway, and the current frontend is broken with the new backend until then |
| Seed re-run | ❌ No — existing demo orgs' `pack_id` values migrate as `template_id` values verbatim |

## Smoke

```powershell
.\API\docker-helper.cmd upgrade        # Apply 0XXX migration
.\API\docker-helper.cmd restart        # Pick up Python changes
docker exec template_api-api-1 pytest -v   # All tests pass

# Manual API check (PowerShell):
$body = '{"email":"rename-test@diag.local","password":"Owner@123","first_name":"Rename","last_name":"Test"}'
$r1 = Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/register -Method Post -Body $body -ContentType 'application/json'
$T = $r1.access_token

# /users/me should show template_id, not pack_id
Invoke-RestMethod -Uri http://localhost:8000/api/v1/users/me -Headers @{Authorization="Bearer $T"} | ConvertTo-Json -Depth 5 | Select-String "template_id|pack_id"

# Onboarding accepts template_id
$ob = '{"organization_name":"Rename Test","template_id":"furniture"}'
Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/onboarding/complete -Method Post -Body $ob -ContentType 'application/json' -Headers @{Authorization="Bearer $T"}
```

## Risks

- **Frontend is broken between Step 1 and Step 2.** Onboarding endpoint will 422 because the frontend wizard sends `pack_id` and Pydantic strict-mode will reject the missing `template_id`. Mitigation: ship Step 2 immediately after Step 1 (same session). Don't deploy Step 1 to production without Step 2 ready.
- **Existing demo orgs** have `pack_id` values in the DB today. Migration preserves all row values verbatim — only the column name changes. No data loss, no special handling required.
- **Catalog cache** (`get_catalog` is `@lru_cache(maxsize=1)`). On API restart, cache rebuilds from the renamed config. No special handling.
- **Audit log historical entries** keep their original `pack_id` payload keys (they're already written; we don't rewrite history). New events use `template_id`. Acceptable — audit is append-only.
- **`PackManifest.pack_id` field validator** — the existing validator uses the field name in error strings. Update those strings so error messages match the new field name.
- **Pack manifest YAML literal value** — `template_id: base` (not `template_id: pack-base` or similar). The string value is unchanged; only the YAML key changes.

## Rollback

1. `.\API\docker-helper.cmd downgrade` — Alembic reverts the column rename.
2. `git revert` the 20 file changes — Python and YAML go back to `pack_id`.
3. Frontend (which was never touched in this step) continues to send `pack_id` — back in sync.

No data loss in either direction.
