# Step 3 — Backend: `/standard-fields/{entity}/render` merge endpoint

**Goal:** Expose a single read endpoint that returns the **merged** view of standard fields for an entity: registry defaults coalesced with the caller-org's override rows. This is what every form modal calls on open. Mirrors the existing `/custom-fields/{entity}/render` shape so a future iteration can unify both into the dynamic-form renderer.
**Track:** Standard Field Overrides
**Status:** COMPLETED — `StandardFieldRendered` + `…ListResponse` schemas, `_merge()` + `_is_overridden()` + `_coalesce_numeric()` helpers, `render_for_entity()`, and `GET /{entity}/render` shipped. Render is gated by `get_current_user` only (no manage permission) — confirmed live: Employee can call render, only management endpoints require `settings.standard_fields.manage`. Sort is `(effective display_order, registry insertion index)` — stable across requests. `is_overridden` is `override_row is not None AND any non-NULL override column` (handles empty-row edge case so the UI doesn't surface a no-op Reset button). 20 new unit tests (40 total) cover all coalescing paths, Decimal→float casting, sort tiebreak, and the unknown-entity early-fail. End-to-end live curl verified: PUT override → render shows merged values → DELETE → render back to defaults. Also surfaced + applied the existing-orgs backfill SQL for `settings.standard_fields.manage` (13 Owner/Admin roles granted) — flagged in Step 1 as deferrable to Step 4 but unblocked smoke-testing here.
**Depends on:** Step 1 (registry), Step 2 (override table + endpoints).

---

## Scope

In-scope:

- One new endpoint `GET /api/v1/standard-fields/{entity}/render` open to any authenticated user in the org (no `manage` permission — every form needs it).
- Returns an array of `StandardFieldRendered` items: one per registered field for the entity, with override values merged in.
- Sorted by effective `display_order` (override → registry default), then registered insertion order as tiebreak.
- Hidden fields are **included** in the response (with `is_hidden=true`); the client decides whether to render. This keeps the Settings page's preview honest and lets integrations introspect what the UI currently shows.

Out of scope:

- No new frontend (Step 4–6).
- No caching layer — first pass is a per-request query. Add caching only if Step 7 profiling shows a hotspot (unlikely; one small SELECT per modal open).
- No bulk endpoint to fetch all entities at once. If the Settings page later needs it, add `GET /standard-fields/render` (no entity) in a follow-on step.

## Response shape

```python
# api/src/app/core/standard_fields/schemas.py (extends Step 2)

class StandardFieldRendered(BaseModel):
    entity: str
    field_key: str
    field_type: str           # from registry: "text" | "currency" | ...

    label: str                # effective (override → default)
    placeholder: str | None
    help_text: str | None
    is_required: bool         # effective
    is_hidden: bool           # effective (defaults to false if no override)
    min_value: float | None
    max_value: float | None
    step_value: float | None
    display_order: int

    backend_required: bool    # informational, never overridden
    backend_validators: list[str]  # informational

    is_overridden: bool       # true if any prop differs from registry default — drives a "Reset" button in the Settings UI
    overridable_props: list[str]   # registry-declared whitelist, surfaced so the UI can grey-out the locked knobs

class StandardFieldRenderedListResponse(BaseModel):
    entity: str
    items: list[StandardFieldRendered]
```

## Endpoint

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /api/v1/standard-fields/{entity}/render` | `require_authenticated()` (any logged-in user in the org) | Returns the merged registry+overrides list for the given entity, sorted by `display_order`. 404 if `entity` is not in the registry. |

The endpoint is **deliberately not** gated on `settings.standard_fields.manage` — every form modal in the app calls it. Read access is implicit in being authenticated to the org.

## Service-layer merge

```python
# api/src/app/core/standard_fields/service.py (extends Step 2)

async def render_for_entity(db: AsyncSession, *, org_id: UUID, entity: str) -> list[StandardFieldRendered]:
    registry_defs = registry.list_for_entity(entity)        # ordered by registry insertion
    if not registry_defs:
        raise EntityNotInRegistry(entity)

    overrides_by_key = await _fetch_overrides_map(db, org_id=org_id, entity=entity)
    # -> dict[field_key, StandardFieldOverride]

    merged = [_merge(d, overrides_by_key.get(d.field_key)) for d in registry_defs]

    # Effective display_order may differ from registry insertion if user reordered.
    merged.sort(key=lambda m: (m.display_order, registry_defs.index(...)))   # stable
    return merged
```

The `_merge` helper coalesces each prop: override value wins if non-NULL, else registry default. `is_overridden` is set if *any* coalescing came from the override side. `overridable_props` is copied straight from the registry (informational).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/standard_fields/schemas.py` | modified — add `StandardFieldRendered` + `StandardFieldRenderedListResponse`. |
| `api/src/app/core/standard_fields/service.py` | modified — add `render_for_entity()` and the `_merge` helper. |
| `api/src/app/core/standard_fields/router.py` | modified — add the new `GET /{entity}/render` endpoint. |
| `api/tests/test_standard_field_overrides.py` | modified — extend with render-endpoint tests (see below). |

**4 modified files. No new files. No migrations.**

## Plan

1. Extend `schemas.py` with the rendered shapes.
2. Extend `service.py` with `render_for_entity` + `_merge`. Fetch the overrides for the entity in one SELECT, build the dict, then iterate the registry list to assemble merged rows. Keep the query inside the request session so RLS scopes it to `org_id`.
3. Extend `router.py` with the new endpoint. Permission gate is just `require_authenticated` (no `settings.standard_fields.manage` — see Scope).
4. Tests: see below.

## Tests

Extend `api/tests/test_standard_field_overrides.py`:

- **Render with no overrides:** GET `/standard-fields/lead/render` on a fresh org → every registered lead field is returned with its registry defaults; `is_overridden=false` for all.
- **Render after upsert:** PUT `lead/budget` with `{label: "Project Budget (₹)", min_value: 5000}`, then GET render. Budget row shows the new label + min; `is_overridden=true`; other fields still default.
- **Display-order reflow:** PUT `lead/expected_close_date` with `display_order: 0` (move it to top); GET render returns fields in the new order. Other fields' order stays stable.
- **Hidden field still present:** PUT `contact/source` with `is_hidden: true`; GET render still lists `source` with `is_hidden=true` (client filters; server returns everything).
- **Permissioning:** Employee (no `settings.standard_fields.manage`) **can** still call render — assert 200. They cannot call the management endpoints from Step 2 (already pinned).
- **Cross-tenant isolation:** Org A's user calling render against org A sees org A's overrides; an org B user sees org B's. (RLS check.)
- **Unknown entity:** GET `/standard-fields/unicorn/render` → 404.

## Smoke

```
docker exec template_api-api-1 pytest tests/test_standard_field_overrides.py -v

# Verify the merge end-to-end:
curl -s -H "Authorization: Bearer $OWNER" \
     http://localhost:8000/api/v1/standard-fields/lead/render | jq

# Expected: array of 3+ items; budget shows registry defaults
# (or, if Step 2's pre-seed SQL was run, "Project Budget (₹)" with is_overridden=true).
```

Sample expected payload:

```json
{
  "entity": "lead",
  "items": [
    {
      "entity": "lead", "field_key": "pipeline_stage", "field_type": "select",
      "label": "Pipeline stage", "placeholder": null, "help_text": null,
      "is_required": true, "is_hidden": false,
      "min_value": null, "max_value": null, "step_value": null,
      "display_order": 0,
      "backend_required": false, "backend_validators": [],
      "is_overridden": false,
      "overridable_props": ["label", "help", "display_order"]
    },
    {
      "entity": "lead", "field_key": "budget", "field_type": "currency",
      "label": "Project Budget (₹)", "placeholder": "0.00", "help_text": null,
      "is_required": true, "is_hidden": false,
      "min_value": 5000.0, "max_value": null, "step_value": 0.01,
      "display_order": 1,
      "backend_required": false, "backend_validators": ["must be ≥ 0"],
      "is_overridden": true,
      "overridable_props": ["label", "placeholder", "help", "required", "hidden", "min", "max", "step", "display_order"]
    }
  ]
}
```

## Risks

- **N+1 query trap:** naive code that loops the registry and SELECTs per-field would do as many round trips as there are fields. Mitigation: one SELECT per render call, fetched into a dict; iterate the registry against the dict. (Spelled out in Plan step 2.)
- **Stable sort across renders:** if two fields share `display_order`, ordering must be deterministic across requests so the UI doesn't jitter. Mitigation: secondary sort key = registry insertion order (`registry_defs.index(...)` or carry a numeric `default_display_order` from the registry).
- **Frontend cache invalidation:** when an Owner saves an override in the Settings page (Step 4), every open form modal in the app needs to re-render. The Settings page emits a signal/event after save; modals subscribed re-fetch. Spelled out in Step 4 + Step 5/6.
- **Public render endpoint surface area:** the response includes registered-but-hidden fields plus their `backend_validators` hints. This is intentional (Settings UI needs them) and not sensitive (it's metadata about your own org's form). No leakage concern.

## Rollback

Revert the four modified files. The endpoint disappears; modals using it (after Step 5/6) break — ship Steps 3 → 6 together or wrap modal fetches with a fallback. Tests revert with the file.
