# Step 3 — Backend: `import_presets` per source platform

**Goal:** Add an `import_presets` table seeded with one preset per known source platform (Zoho, HubSpot, Salesforce, Freshsales, Generic CSV). A preset is a `{csv_column_pattern → crm_field_key}` dict the frontend uses as the default mapping when a user uploads an export from that platform. Per-org user-saved presets are also supported so an org can lock its team's "Excel template v3" mapping.
**Track:** Bulk Import
**Status:** Done — `import_presets` table shipped via migration `0042_import_presets` with custom RLS (system rows readable by every org via `is_system OR org_id = current_setting(...)`, writes restricted to org-owned rows). Seed migration `0043_seed_system_import_presets` populates 5 system presets (Zoho / HubSpot / Salesforce / Freshsales / Generic CSV). `targets.py` enumerates 8 standard targets + per-org `custom_data.*` from `custom_field_definitions`. `presets.py` ships `list_presets` / `create_preset` / `delete_preset` with auto-name `<platform> vN`, mapping validation against the shared target whitelist, and audit events `import_presets.created` / `import_presets.deleted`. Router gains `GET /targets`, `GET /presets?source_platform=`, `POST /presets`, `DELETE /presets/{id}` — all four declared BEFORE `/{import_id}` to avoid FastAPI's UUID path-param swallowing "presets"/"targets". End-to-end verified: 8 targets returned with correct labels/types/required, system Zoho visible to all orgs, org-owned create succeeds + lists with system first, validation rejects bad/unknown targets (422), unique name collision (409), system-preset delete rejected (403), cross-org isolation holds, auto-name picks `zoho v1` → `zoho v2`. Migrations round-trip clean. Notable adaptations: (a) `ImportPreset` model does NOT use `TenantScoped` mixin (mixin enforces `org_id NOT NULL` + auto-filter that would hide system rows); service queries filter explicitly with `(is_system OR org_id = ctx)`. (b) `targets.py` ships an inline `_STANDARD_TARGETS` table rather than pulling from `core.standard_fields` registry — the two whitelists answer different questions (overridable vs. writable; `contact.notes` is writable but not registered as overridable). (c) No `core/audit/events.py` per codebase convention.
**Depends on:** Step 1 (`lead_imports` + `source_platform` field), Step 2 (target-field validation logic — reused for preset validation).

---

## Scope

In-scope:

- Alembic migration adding `import_presets` table.
- Seed migration with one **system** preset per known `source_platform` (rows with `org_id IS NULL` — special case for system-owned presets).
- SQLAlchemy `ImportPreset` model + Pydantic schemas.
- `GET /api/v1/leads/import/presets?source_platform=zoho` — returns the system preset for that platform plus any org-owned presets for that platform.
- `POST /api/v1/leads/import/presets` — create an org-owned preset (`{name, source_platform, mapping}`). Auto-named "<source_platform> v<N>" if `name` omitted.
- `DELETE /api/v1/leads/import/presets/{id}` — only org-owned presets (system presets reject with 403).
- `GET /api/v1/leads/import/targets` — returns the full list of mappable CRM fields including standard lead fields, standard contact fields, and the org's custom fields. Frontend uses this to populate the per-row mapping dropdowns.
- The five system seed mappings (best-effort starting points; refined over time as customers report mis-mappings):

  | Platform | Sample column → CRM field mappings |
  |---|---|
  | `zoho` | `Lead Name → contact.full_name`, `Email → contact.email`, `Phone → contact.phone`, `Mobile → contact.phone`, `Lead Source → notes`, `Annual Revenue → budget`, `Lead Status → pipeline_stage` |
  | `hubspot` | `First Name + Last Name → contact.full_name (concat)`, `Email → contact.email`, `Phone Number → contact.phone`, `Lifecycle Stage → pipeline_stage`, `Amount → budget` |
  | `salesforce` | `Name → contact.full_name`, `Email → contact.email`, `Phone → contact.phone`, `Lead Status → pipeline_stage`, `Annual Revenue → budget` |
  | `freshsales` | `Full Name → contact.full_name`, `Email → contact.email`, `Mobile → contact.phone`, `Lead Stage → pipeline_stage` |
  | `generic_csv` | (empty — no defaults; user maps everything) |

  *Concat-style "First Name + Last Name → contact.full_name"* is **out of scope** for v1. List each as a single column instead (`First Name → contact.full_name`) and document in the README that HubSpot users often need to manually combine first/last in their CSV before upload. Removing this trade-off requires a transform DSL — separate future task.

Out of scope:

- No preset versioning history.
- No "share preset across orgs" — every org gets its own copy if it wants to customise the system default (clone-on-edit).
- No frontend.

## The `import_presets` table

```sql
CREATE TABLE import_presets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID REFERENCES organizations(id),    -- NULL for system presets
    source_platform TEXT NOT NULL,                        -- matches lead_imports.source_platform
    name            TEXT NOT NULL,
    mapping         JSONB NOT NULL,                       -- {csv_column: crm_field_key | null}
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,
    created_by      UUID REFERENCES users(id),            -- NULL for system rows
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX import_presets_org_platform_name_uq
    ON import_presets (COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid), source_platform, name);

CREATE INDEX import_presets_lookup_idx
    ON import_presets (source_platform, org_id) WHERE org_id IS NOT NULL;

-- RLS — system rows readable by all orgs, org-owned rows isolated
ALTER TABLE import_presets ENABLE ROW LEVEL SECURITY;
CREATE POLICY import_presets_read ON import_presets FOR SELECT
    USING (is_system OR org_id = current_setting('app.org_id', true)::uuid);
CREATE POLICY import_presets_write ON import_presets FOR ALL
    USING (NOT is_system AND org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (NOT is_system AND org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_import_presets.py` | created |
| `api/alembic/versions/0XXY_seed_system_import_presets.py` | created — data-only migration with one INSERT per platform |
| `api/src/app/core/leads/imports/presets.py` | created — `PresetService` |
| `api/src/app/core/leads/imports/router.py` | modified — add presets endpoints |
| `api/src/app/core/leads/imports/schemas.py` | modified — `PresetCreate`, `PresetRead`, `MappingTarget` |
| `api/src/app/core/leads/imports/targets.py` | created — `available_targets(org_id) -> list[MappingTarget]` |
| `api/tests/test_import_presets.py` | created |

**7 files, 2 migrations.** Inside rule-8 budget.

## Plan

1. Migration 1: create the table + RLS. Migration 2: seed the five system rows (transactional, idempotent on re-run via `ON CONFLICT DO NOTHING` on the unique index).
2. Build `targets.py`. Returns:
   - All standard lead columns surfaced via the standard-fields registry (those with `overridable_props != frozenset()`).
   - All standard contact columns ditto.
   - All `custom_field_definitions` rows scoped to the org, as `custom_data.<key>`.
3. Build `PresetService` with `list(source_platform)`, `create(name, source_platform, mapping)`, `delete(id)`. `create` validates the mapping against `available_targets()` (every value either `null` or in the targets set).
4. Wire endpoints. Permission gate: read = `leads.import`, write = `leads.import`.
5. Tests.

## Tests

`api/tests/test_import_presets.py`:

- **System presets visible to every org:** Org A sees the `zoho` system preset. Org B sees the same one. Neither org can edit/delete it.
- **Org-owned isolation:** Org A creates a custom Zoho preset "My Zoho". Org B does not see it.
- **Create validates mapping:** mapping with `{"X":"id"}` → 422 (id is system-managed).
- **Create validates against custom fields:** mapping with `{"X":"custom_data.unknown_key"}` → 422.
- **Create with custom field exists:** seed `custom_field_definitions` with key `industry` → mapping `{"Industry":"custom_data.industry"}` → 201.
- **Unique name per (org, platform):** create "My Zoho" twice in same org → second 409.
- **Auto-name fallback:** create without `name` → name is `zoho v1` (then `zoho v2` on next).
- **Delete system preset rejected:** as Owner, `DELETE /presets/{system-zoho-id}` → 403.
- **Targets endpoint includes everything:** assert standard lead fields + standard contact fields + org custom fields all in the response.

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_import_presets.py -v

# Sanity: as Owner, list zoho presets
curl http://localhost:8000/api/v1/leads/import/presets?source_platform=zoho -H "Authorization: Bearer $token"
# Expect: array with at least one entry whose is_system=true.

# Sanity: targets endpoint
curl http://localhost:8000/api/v1/leads/import/targets -H "Authorization: Bearer $token"
# Expect: array with entries like {key:"contact.full_name",label:"Full name",required:true,custom:false}.
```

## Risks

- **Seed mappings will drift from reality:** real Zoho/HubSpot exports vary by org configuration (custom columns, renamed standard fields). The system preset is a starting point; the mapping UI must let the user override every field. Document this in the user-facing help text on the mapping page (Step 5).
- **System preset upgrades over time:** if we ship a "better" Zoho mapping in a future migration, orgs that cloned the original keep their copy. That's intentional — never silently mutate an org's preset.
- **RLS on system rows:** the read policy uses `is_system OR org_id = ...`. Postgres applies policies as OR by default for SELECT but we should still write the policy as a single permissive policy (one `USING` clause) to be explicit. Double-check the existing project's RLS convention and mirror it.
- **Two migrations for the same logical change:** schema + data seed are split per CLAUDE.md migration conventions (data migrations stay reversible and skippable). Both up/down cleanly.

## Rollback

Reverse both migrations. Delete the new .py files. Revert the schema + router additions. Existing imports in flight do not depend on presets at the commit stage (presets are read-only suggestions for the UI) so no in-flight breakage.
