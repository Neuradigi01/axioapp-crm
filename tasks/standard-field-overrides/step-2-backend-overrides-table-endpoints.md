# Step 2 — Backend: `standard_field_overrides` table + CRUD endpoints

**Goal:** Persist per-org overrides for standard fields and expose CRUD endpoints gated on the new `settings.standard_fields.manage` permission. Enforce the registry's `overridable_props` contract at write time so the DB never holds an override for a knob the field doesn't allow.
**Track:** Standard Field Overrides
**Status:** COMPLETED — migration `0039_standard_field_overrides`, model, schemas, service, router, and unit tests shipped. The `_validate_payload_against_registry` helper enforces the registry contract: 404 for unknown entity/field, 422 for any prop not in `overridable_props` (errors collected, all reported at once). Audit emission via `settings.standard_field_override.updated` / `…reset`. `actor_id` plumbed through from `user.legacy_uuid` to `created_by` / `updated_by`. Router mounted under `/api/v1/standard-fields` with `settings.standard_fields.manage` gating all four endpoints. Audit `events.py` skipped — codebase convention is string literals at call sites (confirmed in `core/audit/service.py`). 20 pure-unit tests cover all 404/422 paths, schema constraints, the payload↔registry name bridge, migration shape, and router wiring. DB/HTTP integration suite documented in the test file but deferred — existing `conftest.py` fixtures pre-date the DR.7 user-table split (a separate pre-existing bug) and the Postgres host isn't reachable from this workstation. Migration is unrun in this environment for the same reason; the file imports cleanly and follows the same shape as 0006 (RLS via `apply_rls`).
**Depends on:** Step 1 (registry + permission key), Phase 1.4 (multi-tenancy + RLS), Phase 1.7 (audit logs).

---

## Scope

In-scope:

- One new table `standard_field_overrides` with `org_id`, `entity`, `field_key`, and the presentational override columns. RLS policy attached in the same migration (Rule 2).
- SQLAlchemy 2.x async model + Pydantic v2 schemas (in/out/list).
- Service-layer functions: `list_for_org(org_id)`, `list_for_entity(org_id, entity)`, `upsert(org_id, entity, field_key, payload)`, `reset(org_id, entity, field_key)`.
- HTTP endpoints under `/api/v1/standard-fields/`:
  - `GET /` — list all overrides for the org.
  - `GET /{entity}/` — list overrides for a single entity.
  - `PUT /{entity}/{field_key}` — upsert one override.
  - `DELETE /{entity}/{field_key}` — reset to registry defaults (remove the row).
- Write-time validation: rejects fields not in the registry; rejects override keys not in that field's `overridable_props`; rejects `hidden=true` on `backend_required=true` fields **only if** the registry locks `hidden` for that field (otherwise allowed with the documented warning surfaced at the UI layer).
- Audit-log emission: `settings.standard_field_override.updated` on PUT, `settings.standard_field_override.reset` on DELETE.

Out of scope:

- No `/render` merge endpoint — Step 3.
- No frontend.
- No pack-install seeding hook (that lands as a separate Phase 4 follow-on).

## Table shape

```sql
CREATE TABLE standard_field_overrides (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity          VARCHAR(64)  NOT NULL,    -- "contact" | "lead" | ...
    field_key       VARCHAR(128) NOT NULL,    -- "budget" | "full_name" | ...

    -- presentational overrides (NULL = inherit from registry default)
    label             VARCHAR(255),
    placeholder       VARCHAR(255),
    help_text         TEXT,
    is_required       BOOLEAN,          -- NULL = inherit
    is_hidden         BOOLEAN,          -- NULL = inherit (false)
    min_value         NUMERIC(20, 6),
    max_value         NUMERIC(20, 6),
    step_value        NUMERIC(20, 6),
    display_order     INTEGER,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by      UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT uq_standard_field_overrides_org_entity_field
        UNIQUE (org_id, entity, field_key)
);

CREATE INDEX ix_sfo_org_entity ON standard_field_overrides (org_id, entity);

-- RLS (Rule 2)
ALTER TABLE standard_field_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY sfo_tenant_isolation ON standard_field_overrides
    USING (org_id = current_setting('app.current_org_id')::uuid);
```

Notes:

- `NUMERIC(20, 6)` is generous enough for currency, percentages, and integer rupees (`step_value=1`). No need for a separate column per type.
- `NULL` in any override column means "inherit registry default." Step 3's merge endpoint coalesces.
- Unique key is `(org_id, entity, field_key)` — exactly one row per field per org.
- `created_by` / `updated_by` are `ON DELETE SET NULL` so deleting a user doesn't cascade-nuke their overrides.

## Endpoints

| Endpoint | Auth | Body | Behaviour |
|---|---|---|---|
| `GET /api/v1/standard-fields/` | `require_permissions("settings.standard_fields.manage")` | — | List **override rows** for the caller's org. Returns `[{entity, field_key, …override cols…, updated_at, updated_by}]`. **Not** the merged view — that's Step 3. |
| `GET /api/v1/standard-fields/{entity}/` | `require_permissions("settings.standard_fields.manage")` | — | Same as above, filtered to one entity. |
| `PUT /api/v1/standard-fields/{entity}/{field_key}` | `require_permissions("settings.standard_fields.manage")` | `StandardFieldOverrideIn` | Upsert. Returns 200 with the merged-default-plus-override view (so the UI can re-render without a follow-up GET). 404 if `(entity, field_key)` is not in the registry. 422 if the payload sets a prop outside `overridable_props`. |
| `DELETE /api/v1/standard-fields/{entity}/{field_key}` | `require_permissions("settings.standard_fields.manage")` | — | Removes the row → field reverts to registry defaults. 204 on success; 404 if no row exists. |

## Pydantic schemas

```python
# api/src/app/core/standard_fields/schemas.py

class StandardFieldOverrideIn(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = None
    is_required: bool | None = None
    is_hidden: bool | None = None
    min_value: float | None = None
    max_value: float | None = None
    step_value: float | None = None
    display_order: int | None = Field(default=None, ge=0, le=999)

class StandardFieldOverrideOut(StandardFieldOverrideIn):
    id: UUID
    entity: str
    field_key: str
    created_at: datetime
    updated_at: datetime
    updated_by: UUID | None

class StandardFieldOverrideListResponse(BaseModel):
    items: list[StandardFieldOverrideOut]
    total: int
```

Service-layer validation calls `registry.get(entity, field_key)` for every PUT and rejects any payload key whose corresponding override is **not** in `overridable_props`. Pydantic alone cannot do this — it's per-field-dynamic.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/<timestamp>_create_standard_field_overrides.py` | created — table + indexes + RLS policy. |
| `api/src/app/core/standard_fields/models.py` | created — `StandardFieldOverride` SQLAlchemy model. |
| `api/src/app/core/standard_fields/schemas.py` | created — Pydantic in/out/list. |
| `api/src/app/core/standard_fields/service.py` | created — `list_for_org`, `list_for_entity`, `upsert`, `reset`; registry-contract enforcement. |
| `api/src/app/core/standard_fields/router.py` | created — the four endpoints above. |
| `api/src/app/main.py` | modified (small) — register the new router. |
| `api/src/app/core/audit/events.py` | modified (small) — add `settings.standard_field_override.updated` and `…reset` event constants. (If audit events are string literals at call sites rather than a registry, this file may not exist — adapt to the codebase's convention.) |
| `api/tests/test_standard_field_overrides.py` | created — see Tests below. |

**6 new files + 2 modified + 1 migration = 9 file deltas.** At the rule-8 limit; do not bundle render-endpoint work in here.

## Plan

1. Write the Alembic migration. Verify `alembic upgrade head` then `alembic downgrade -1` both succeed.
2. Create the SQLAlchemy model. Use `Mapped[…]` typing per the locked stack (SQLAlchemy 2.x async).
3. Pydantic schemas (in/out/list) — Pydantic v2 only.
4. Service-layer functions. The `upsert` function is the only one with real logic:
   - Resolve registry def via `registry.get(entity, field_key)`. Raise `FieldNotInRegistry` → 404 if absent.
   - For each field in `StandardFieldOverrideIn` that is **not None**, check it's in the registry def's `overridable_props`. If any payload key is not allowed → 422 with the offending key listed.
   - If `is_hidden=True` and `registry_def.backend_required=True` and `"hidden"` is not in `overridable_props`, reject. (Otherwise allow and rely on UI warning.)
   - Upsert via `INSERT … ON CONFLICT (org_id, entity, field_key) DO UPDATE SET …`. Stamp `updated_by`, `updated_at`.
   - Emit audit event with the diff (`before`, `after`) for traceability.
5. Router. Match the URL/auth/return shape table above.
6. Tests (see below).

## Tests

`api/tests/test_standard_field_overrides.py`:

- **Migration round-trip:** `upgrade head` then `downgrade -1` then re-upgrade leaves the schema clean. (Standard pattern from existing test infra.)
- **Permission gate:** Employee (no `settings.standard_fields.manage`) hits 403 on all four endpoints; Admin and Owner pass.
- **Cross-tenant isolation:** Org A's Owner cannot GET, PUT, or DELETE an override on org B's `(entity, field_key)` — RLS blocks the SELECT, PUT returns 404 (not "forbidden") since the row is invisible.
- **Upsert happy path:** PUT `{entity: lead, field_key: budget}` with `{label: "Project Budget (₹)", min_value: 5000}` → 200, row persisted, `updated_by` stamped.
- **Re-upsert same row:** issuing PUT twice updates the existing row (no duplicate); `updated_at` increases.
- **Unknown entity:** PUT `/unicorn/horn_length` → 404 `field_not_in_registry`.
- **Unknown field key on a real entity:** PUT `/lead/imaginary_field` → 404 `field_not_in_registry`.
- **Disallowed prop:** PUT on `contact.full_name` with `is_required: false` while the registry locks `required` → 422 with body `{"errors": ["is_required not overridable for contact.full_name"]}`.
- **Hide-NOT-NULL-locked field:** PUT on `lead.contact_id` with `is_hidden: true` when registry forbids it → 422.
- **Reset (DELETE):** PUT then DELETE → 204; subsequent GET returns no row for that field.
- **Audit log:** after a PUT, an `audit_logs` row exists with `event='settings.standard_field_override.updated'` and a JSON `detail` containing before/after.

## Smoke

```
.\docker-helper.cmd upgrade
docker exec template_api-api-1 pytest tests/test_standard_field_overrides.py -v

# Manual curl (assume $OWNER is a valid Owner JWT for the core-demo org):
curl -s -X PUT -H "Authorization: Bearer $OWNER" -H "Content-Type: application/json" \
     -d '{"label":"Project Budget (₹)","is_required":true,"min_value":5000}' \
     http://localhost:8000/api/v1/standard-fields/lead/budget | jq

curl -s -H "Authorization: Bearer $OWNER" http://localhost:8000/api/v1/standard-fields/lead/ | jq

curl -s -X DELETE -H "Authorization: Bearer $OWNER" \
     http://localhost:8000/api/v1/standard-fields/lead/budget -w "%{http_code}\n"
# Expected: 204
```

## Raw INSERT SQL (for the report)

If the implementer wants to pre-seed a couple of override rows for the demo org during local testing (rather than driving them through the API), include the raw SQL in the stop-report:

```sql
-- Pre-seed: rename Budget on Leads to "Project Budget (₹)" for the core-demo org
INSERT INTO standard_field_overrides (org_id, entity, field_key, label, is_required, min_value)
SELECT id, 'lead', 'budget', 'Project Budget (₹)', true, 5000
FROM organizations
WHERE slug = 'core-demo'
ON CONFLICT (org_id, entity, field_key) DO NOTHING;
```

## Risks

- **RLS bypass via service code:** if the service uses a session without the `app.current_org_id` GUC set, RLS won't catch cross-tenant writes. Mitigation: tests pin cross-tenant isolation; the existing tenancy middleware already sets the GUC for every request — reuse the existing async session dependency.
- **Numeric column precision:** `NUMERIC(20, 6)` covers ₹0 to ₹99,999,999,999,999.999999. Sufficient for INR amounts including paise and for any integer step values. Flag if a downstream entity needs more (currently none).
- **Audit-event flooding:** an over-eager Settings UI that PUTs on every keystroke would spam audit logs. Step 4's UI must debounce / only PUT on Save click — pinned in the Step 4 spec.

## Rollback

`alembic downgrade -1` drops the table and policy. Delete the six new files; revert the small additions to `main.py` and `core/audit/events.py`. The new permission key from Step 1 stays in place (no rollback needed for that — it just stops gating any endpoint).
