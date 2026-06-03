# Step 1 — Pack catalog endpoint + static config

**Goal:** Expose `GET /api/v1/packs/catalog` returning every CRM template tile — real packs auto-discovered from `packs/*/pack.yaml`, plus placeholder ("Coming soon") packs from a static config file — each tagged `available` or `coming_soon`, ready for the onboarding page to render.

**Track:** Onboarding & Pack Picker Setup
**Status:** COMPLETED
**Depends on:** Furniture pack (`packs/furniture/pack.yaml`) — Done. Pack scanner — Done (used by module_registry).

---

## Scope

Read-only catalog endpoint. No DB writes. No auth gating (the onboarding page may need to fetch this before the user is fully authorized in the org sense; the endpoint is informational and contains no PII).

The endpoint composes its response from two sources:

1. **Real packs** — scan `api/src/app/packs/*/pack.yaml` via the existing pack registry. For each, extract `id`, `name`, `description`, `icon`, `default_currency`, `default_tax_rate`, list of module IDs. Tag `status: "available"`.
2. **Placeholder packs** — read `api/src/app/core/packs/catalog_config.py`, a static Python module listing tiles for verticals not yet built. Tag `status: "coming_soon"`.

Both sources merge into one ordered list, sorted ascending by `display_order`.

## What this does NOT do

- Does **not** modify any existing pack-discovery logic. Reads from it.
- Does **not** modify the `installer.py` contract.
- Does **not** introduce any new pack scaffolding.

## Schema

No new tables. No migrations.

## Backend

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /api/v1/packs/catalog` | optional bearer | Returns `{"packs": [...]}`. Each pack: `{id, name, description, icon, status, default_currency, default_tax_rate, modules_preview, display_order}`. Process-cached after first build (catalog config is static; pack manifests are loaded at startup). |

### Response shape

```json
{
  "packs": [
    {
      "id": "core",
      "name": "Core CRM",
      "description": "Universal CRM for any business — contacts, leads, pipelines, billing.",
      "icon": "briefcase",
      "status": "available",
      "default_currency": "INR",
      "default_tax_rate": 18.0,
      "modules_preview": ["contacts", "leads", "pipelines", "tasks", "billing"],
      "display_order": 0
    },
    {
      "id": "furniture",
      "name": "Furniture CRM",
      "description": "Built for furniture retail — inventory, custom orders, field ops, POS.",
      "icon": "armchair",
      "status": "available",
      "default_currency": "INR",
      "default_tax_rate": 18.0,
      "modules_preview": ["inventory", "custom_orders", "field_ops", "billing"],
      "display_order": 100
    },
    {
      "id": "real_estate",
      "name": "Real Estate CRM",
      "description": "Site visits, RERA tracking, channel partners, brokerage management.",
      "icon": "home",
      "status": "coming_soon",
      "default_currency": "INR",
      "default_tax_rate": 5.0,
      "modules_preview": ["listings", "site_visits", "channel_partners", "brokerage"],
      "display_order": 200
    }
    // ... clinic, sales, automotive, salon, fitness, education, hospitality
  ]
}
```

### Catalog config file

Create `api/src/app/core/packs/catalog_config.py`:

```python
# Static catalog of placeholder ("Coming soon") verticals shown on the onboarding page.
#
# Real packs are auto-discovered by scanning api/src/app/packs/*/pack.yaml at startup —
# do NOT list them here. When a placeholder pack is fully built (manifest + installer +
# modules + UI), remove its entry from this file and the auto-discovery will replace it
# as `status: "available"`.
#
# To add a new vertical placeholder: add one dict to PLACEHOLDER_PACKS with the next
# available display_order (in increments of 100). No code change anywhere else.

PLACEHOLDER_PACKS = [
    {
        "id": "real_estate",
        "name": "Real Estate CRM",
        "description": "Site visits, RERA tracking, channel partners, brokerage management.",
        "icon": "home",
        "default_currency": "INR",
        "default_tax_rate": 5.0,
        "modules_preview": ["listings", "site_visits", "channel_partners", "brokerage"],
        "display_order": 200,
    },
    {
        "id": "clinic",
        "name": "Clinic / Dental CRM",
        "description": "Patient records, appointments, treatment plans, recall reminders.",
        "icon": "heart-pulse",
        "default_currency": "INR",
        "default_tax_rate": 0.0,
        "modules_preview": ["patients", "appointments", "treatment_plans", "recalls"],
        "display_order": 300,
    },
    {
        "id": "sales",
        "name": "Sales CRM",
        "description": "Generic B2B sales pipeline — deals, quotes, forecasting, territory.",
        "icon": "trending-up",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": ["deals", "quotes", "forecasting", "territory"],
        "display_order": 400,
    },
    {
        "id": "automotive",
        "name": "Automotive CRM",
        "description": "Car dealerships and service centers — test drives, service bookings, AMC.",
        "icon": "car",
        "default_currency": "INR",
        "default_tax_rate": 28.0,
        "modules_preview": ["inventory", "test_drives", "service_bookings", "amc"],
        "display_order": 500,
    },
    {
        "id": "salon",
        "name": "Salon & Spa CRM",
        "description": "Stylist bookings, packages, loyalty points, retail.",
        "icon": "scissors",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": ["bookings", "stylists", "packages", "loyalty"],
        "display_order": 600,
    },
    {
        "id": "fitness",
        "name": "Fitness CRM",
        "description": "Gym memberships, trainer schedules, attendance, diet plans.",
        "icon": "dumbbell",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": ["memberships", "trainers", "attendance", "diet_plans"],
        "display_order": 700,
    },
    {
        "id": "education",
        "name": "Education CRM",
        "description": "Coaching institutes and schools — admissions, batches, fees, parent comms.",
        "icon": "graduation-cap",
        "default_currency": "INR",
        "default_tax_rate": 0.0,
        "modules_preview": ["admissions", "batches", "fees", "parent_comms"],
        "display_order": 800,
    },
    {
        "id": "hospitality",
        "name": "Hospitality CRM",
        "description": "Hotels and restaurants — reservations, guest profiles, loyalty, feedback.",
        "icon": "utensils",
        "default_currency": "INR",
        "default_tax_rate": 18.0,
        "modules_preview": ["reservations", "guests", "loyalty", "feedback"],
        "display_order": 900,
    },
]
```

### Service composition

`api/src/app/core/packs/service.py::get_catalog()`:

1. Load real packs via the existing pack-registry scanner. For each, build a `CatalogTile` with `status="available"` and `display_order` derived from a stable position (0 for core, 100 for furniture, etc., or fallback to alphabetic).
2. Load `PLACEHOLDER_PACKS` from `catalog_config.py`. For each, build a `CatalogTile` with `status="coming_soon"`.
3. **Collision rule:** if a placeholder ID matches a real pack ID, the real pack wins — drop the placeholder. (This is the migration path when a placeholder becomes real.)
4. Sort by `display_order` ascending.
5. Return the merged list.

## Frontend

None this step. Step 3 consumes this endpoint.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/packs/catalog_config.py` | created |
| `api/src/app/core/packs/router.py` | modified — add `GET /catalog` route |
| `api/src/app/core/packs/service.py` | modified — add `get_catalog()` composing real + placeholder packs |
| `api/src/app/core/packs/schemas.py` | modified — `CatalogTile` and `CatalogResponse` Pydantic models |
| `api/tests/test_packs_catalog.py` | created |

**5 files total.** Within per-step rule.

## Tests

`api/tests/test_packs_catalog.py`:

- **Real packs present:** GET catalog → response contains `id="furniture"` (and `core` if it exists as a real pack) with `status="available"`.
- **Placeholders present:** response contains every entry from `PLACEHOLDER_PACKS` with `status="coming_soon"`.
- **No duplicates:** if `PLACEHOLDER_PACKS` contains an ID that matches a real pack, the real pack appears (with `available`) and the placeholder is dropped. Verify by temporarily adding `{"id": "furniture", ...}` to the config and asserting only one `furniture` tile is returned.
- **Order:** response is sorted ascending by `display_order`. Furniture (100) before real_estate (200) before clinic (300).
- **Shape stable:** every tile has the same set of keys (`id`, `name`, `description`, `icon`, `status`, `default_currency`, `default_tax_rate`, `modules_preview`, `display_order`).
- **No auth needed:** unauthenticated GET returns 200.

## Smoke

```powershell
.\API\docker-helper.cmd up
curl http://localhost:8000/api/v1/packs/catalog
```

Expect: JSON list including at least `furniture` (available, 100), then 8 `coming_soon` entries with display_order 200–900. (`core` appears with display_order 0 if a real `core/pack.yaml` exists; if not, it appears only after Step 2 adds a core pack manifest — confirm at step kickoff.)

## Risks

- **Real-pack auto-discovery may not be exposed as a public helper.** `api/src/app/core/module_registry.py` scans for `module.py` files but may not scan for `pack.yaml`. If so, this step needs a small `pack_registry.py::scan_packs()` helper that walks `packs/*/pack.yaml` and parses each. Confirm at kickoff before writing the service.
- **Core as a "real pack":** if no `api/src/app/packs/core/pack.yaml` exists today, Core CRM either needs to be added to `PLACEHOLDER_PACKS` *with* `status` overridden to `"available"` (slight hack), or a thin `packs/core/pack.yaml` should be created (cleaner — defines universal defaults like INR currency, GST 18%, standard sales pipeline stages). Recommend the cleaner option but decide at kickoff to avoid scope creep into Step 2.
- **Catalog as Python, not YAML.** Chose Python over YAML so the config is type-checked and IDE-discoverable. If non-engineer edits are desired later, swap to `catalog.yaml` — one-line change in `service.py`.

## Rollback

Delete the 5 files. Catalog config is read-only metadata — no data to migrate, nothing to undo.
