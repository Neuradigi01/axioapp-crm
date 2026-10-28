# Step 4.1 — Pack manifest infrastructure

**Goal:** Define the `pack.yaml` schema. YAML loader + validator. Implement `installer.py` reading the manifest and seeding pipelines, stages, custom field defs, roles, lead sources, call outcomes, defaults. Idempotent.
**Phase:** 4
**Depends on:** 2.9, 2.1, 1.5, 3.11
**Status:** COMPLETED

## Scope
**In-scope:**
- `api/src/app/core/packs/manifest.py` — Pydantic v2 schema for `pack.yaml`:
  - `pack_id`, `version`, `display_name`
  - `pipelines: [{key, name, stages: [{key, name, color, display_order, is_won, is_lost}]}]`
  - `custom_fields: [{entity_type, field_key, field_label, field_type, options, is_required, display_order, validation}]`
  - `roles: [{key, name, permissions: [str]}]`
  - `lead_sources: [{key, label}]`
  - `call_outcomes: [{key, label, color, display_order}]`
  - `defaults: {currency, tax_rate, timezone, review_source, ai_personality, ai_welcome_message}`
  - `follow_up_schedule: [{day_offset, channel, template}]`
  - `module_permissions: {module_id: [perm_keys]}` — used to populate `role_permissions` per role.
- `api/src/app/core/packs/loader.py` — loads YAML, validates, returns `PackManifest`.
- `api/src/app/core/packs/installer.py` — `install(org_id, manifest)`: idempotent seed. Each section runs in its own try/except + audit log.
- CLI: `python -m src.app.scripts.install_pack --org <slug> --pack <pack_id> --version <ver>`.
- `pack_id` and `pack_version` written to `organizations.pack_id` + `pack_version` after install.

**Out of scope:**
- The actual furniture `pack.yaml` content — 4.2.
- Pack-installer UI — out of project scope.

## Files to touch
- `api/src/app/core/packs/{__init__,manifest,loader,installer}.py` (created)
- `api/src/app/scripts/install_pack.py` (created)

## Plan
1. Define Pydantic schema. Reject duplicate keys within a section.
2. Loader: read YAML, validate, return `PackManifest`. Errors include line/column when possible.
3. Installer steps (each idempotent):
   - Pipelines + stages (upsert).
   - Custom field defs (upsert; source=`pack`, pack_id set).
   - Roles + role_permissions (upsert).
   - Lead sources (config table — added here if not yet; seeds value table).
   - Call outcomes (upsert).
   - Org settings defaults (apply only if not yet customized).
4. Audit log per section.

## Tests to add
- `tests/test_pack_manifest_validation.py`
- `tests/test_pack_installer.py` — re-run installer twice; second run is a no-op.

## Verification checklist
**Backend:**
- create a tiny test manifest fixture, call installer for a fresh org → tables populated.
- re-run → no duplicates.

## Self-check (10 rules)
- [ ] Rule 7: pack manifest is the source of truth.
- [ ] Idempotent.

## Stop & report
Await "proceed" before Step 4.2.
