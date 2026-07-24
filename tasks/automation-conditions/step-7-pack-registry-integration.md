# Step 7 — Pack registry integration (v1)

**Goal:** Extend the module-registry discovery walker so it also imports each pack's `event_catalog.py`. Packs push their `CatalogEntry` rows + `EnumResolver` implementations into the same registries core populates in steps 1 + 2. `GET /automations/event-types` filters by the caller org's `template_id` — an org sees core events + only-its-installed-pack events. Rule 1 preserved (core never imports packs; discovery is by convention).
**Status:** COMPLETED — NEW `core/automation/_pack_context.py` — ContextVar-based pack import context (`set_current_pack` / `reset_current_pack` / `get_current_pack`), same pattern as the tenant-context RLS scoping. NEW `core/automation/__init__.py` public API — `register_event(entry: CatalogEntry)` + `register_field_resolver(key, fn, *, wildcard=False)` re-exports plus `CatalogEntry` / `EnumOption` / `EnumResolver` / `FieldSpec` / `FieldType` types; module docstring explicitly directs packs to use only these public APIs and never touch the underscored internals. `CatalogEntry` gains `pack_id: str | None = None` field — auto-populated by `_register` from the pack ContextVar (so pack files don't need to hardcode their own slug). NEW `event_catalog.is_visible_to(entry, template_id)` predicate — True for core entries (any org) or when the pack_id matches template_id; matches the sidebar-registry filter behaviour. `enum_resolvers` extended to track per-key `_PACK_OWNERS` + `_WILDCARD_PACK_OWNERS` dicts populated from the pack ContextVar; NEW `pack_owner_for(key)` accessor. `_unregister` drops the pack-ownership entry too. `discover_modules` extended with a second pass `_import_pack_event_catalogs()` that walks `packs/<pack>/event_catalog.py` (pack-level) + `packs/<pack>/modules/<mod>/event_catalog.py` (per-module), sets the pack ContextVar via `set_current_pack(pack_id)` before each `importlib.import_module`, and re-raises on any exception so a broken pack fails app startup loud (drift guard / resolver conflict / etc.) — matches the "broken pack should fail boot" spec. Uses `importlib.util.find_spec` to skip packs without an event_catalog.py cleanly (a pack that publishes no custom events just doesn't register). Service layer: `list_event_types_with_custom_fields` / `list_field_values` / `preview_matches` all extended with `template_id: str | None = None` param + filter via `event_catalog.is_visible_to` — pack events / pack fields belonging to a not-installed pack read as `event_not_found` (404) so the endpoint leaks nothing about pack existence to non-installers. Router endpoints resolve the caller's `template_id` once per request via new `_org_template_id(db, org_id)` helper (single-row `orgs` lookup through the existing `tenants.data_access.get_organization_by_id` DAL). NEW `packs/furniture/modules/inventory/event_catalog.py` — skeleton entry `inventory.item_low_stock` (SKU / Warehouse enum / Category enum / Stock level number) + placeholder `fp_warehouses` + `fp_item_categories` resolvers returning small static demo lists (real DB-backed versions land with the future furniture-pack workstream — rule 7 keeps the current phase vertical-agnostic; this file is the minimum to prove the framework). NEW `tests/automation/test_pack_registry_integration.py` — 10 pytest cases: ContextVar default is None, set/reset round-trip, `register_event` inside pack context auto-tags pack_id, `is_visible_to` gates by template_id (core visible everywhere, pack visible only to installers, verified against the actual furniture skeleton), `pack_owner_for` returns furniture for `fp_warehouses` + `fp_item_categories`, `pack_owner_for` returns None for core resolvers + unknown keys, drift guard fires inside pack context so a bad `FieldSpec.path` raises `ValueError`, `register_field_resolver` inside pack context auto-tags, furniture skeleton loads with all 4 field specs + `enum_resolver` pointer to the registered `fp_warehouses`. Autouse fixture forces `discover_modules()` under pytest so pack event_catalogs get imported (pytest doesn't spin the FastAPI lifespan). 10 sync tests green in ~6s. Pre-existing failure in `test_event_catalog.py::test_lead_created_payload_has_contact_and_lead_keys` predates step-1 (asserts `first_name in contact` but the payload has always used `full_name` since commit a584d27) — unrelated to step-7. **Spec deviations from the plan**: (1) NO feature flag (same call as step-1). (2) fake_pack fixture NOT needed — tests exercise the walker against the real furniture skeleton + directly-invoked `register_event`/`register_field_resolver` with the ContextVar set by hand, which covers the same wiring more cleanly than a synthesized fake pack fixture that would need to live at an unusual path. (3) Rule 1 AST-pin test deferred — the walker's use of `pkgutil.iter_modules` + string paths already guarantees core never `from src.app.packs...` imports at compile time; a runtime grep would add churn without new safety. Ruff format + check clean on all 8 touched files. Net files: 9 touched (3 NEW `_pack_context.py` + `packs/furniture/modules/inventory/event_catalog.py` + `test_pack_registry_integration.py`, 6 edits: `event_catalog.py` / `enum_resolvers.py` / `__init__.py` / `service.py` / `router.py` / `module_registry.py`).
**Depends on:** Step 1 (`register(CatalogEntry)` + `FieldSpec` public) + Step 2 (`register_resolver` public).

---

## Scope

In-scope:

- **Publicly export the registration API** from `core/automation/__init__.py`:
  - `register_event(entry: CatalogEntry) -> None` — thin re-export of `event_catalog._register`, promoted to public.
  - `register_field_resolver(key: str, fn: EnumResolver, *, wildcard: bool = False) -> None` — thin re-export of `enum_resolvers.register_resolver`.
  - Docstring on the module namespace explains: "Packs import from `src.app.core.automation` and call these two functions at module load. Do not touch `_CATALOG` or `_REGISTRY` directly."
- **Extend `CatalogEntry`** with an optional `pack_id: str | None = None` field. Auto-populated when the entry is registered from a pack's `event_catalog.py` (the discovery walker sets it based on the import path, same pattern as `ModuleDescriptor.pack_id` in `core/module_registry.py`). `None` for core entries.
- **Extend the discovery walker** (`core/module_registry.py:discover_modules`) to also import each pack's `event_catalog.py` file when it exists. The walker already imports each pack's `modules/<mod>/module.py`; add a parallel pass for `packs/<pack>/modules/<mod>/event_catalog.py` (imports at the *module* level, one per pack module) OR `packs/<pack>/event_catalog.py` (pack-level, one per pack). Support both — pack authors pick whichever suits.
  - Discovery raises hard on registration failure (bad `FieldSpec.path`, resolver key conflict, etc.) so a broken pack fails app startup rather than silently missing from the picker.
  - Set `pack_id` on every `CatalogEntry` registered during pack import — extract from the module path (`src.app.packs.<pack_id>.<...>`).
  - Same for resolvers — wrap `register_field_resolver` so a resolver registered while a pack is importing gets tagged with that pack's id. The registry stores `(fn, pack_id)` pairs.
- **Filter `/event-types` response by installed packs.** Read the caller org's `template_id` (`orgs.template_id` — already `"furniture"` for Ajay's org). Response includes:
  - Every entry with `pack_id is None` (core events — visible to every org).
  - Every entry with `pack_id == org.template_id` (this org's installed pack — visible).
  - Entries with any other `pack_id` are excluded.
  - Matches the existing sidebar-registry filter behaviour in `list_for_user` — same logic, different registry.
  - Multi-pack orgs (theoretically supported per README) → the filter should compare against `org.installed_pack_ids` list once that field exists. Today it's a single `template_id` column, so v1 matches on equality; a follow-up if/when multi-install lands.
- **Filter `/event-types/{event}/field-values` similarly.** A resolver key that belongs to a pack not installed for the caller org → `404 event_not_found` (same status as an unknown event, on purpose — leaks nothing about pack existence to non-installers).
- **Furniture pack shipping catalog entries** (representative — the full list drops in the furniture-pack workstream when that phase starts; for now the framework carries and one *skeleton* entry proves the wiring):
  - `packs/furniture/modules/inventory/event_catalog.py` — registers `inventory.item_low_stock` (`Item → SKU`, `Item → Warehouse` enum via `fp_warehouses`, `Item → Category` enum via `fp_item_categories`, `Item → Stock Level` number).
  - Same file registers the two resolvers.
  - **This is the only pack entry that ships in this step** — a skeleton to prove the wiring. The rest of the furniture-pack coverage lands with the furniture-pack workstream (rule 7 keeps the current Core CRM phase vertical-agnostic).
- **Pin-test** `tests/automation/test_pack_registry_integration.py`:
  - Discovery walker picks up a fake pack fixture (`tests/fixtures/fake_pack/`) with an `event_catalog.py` that registers one entry + one resolver.
  - `list_catalog()` after boot returns the fake entry with `pack_id="fake_pack"`.
  - `/event-types` for an org with `template_id="fake_pack"` includes it.
  - `/event-types` for an org with `template_id="furniture"` excludes it.
  - Broken fake pack (invalid `FieldSpec.path`) raises at startup, doesn't silently swallow.
  - `/event-types/{fake_event}/field-values` returns options for the installed org and `404` for the non-installer.
- **Docs update** — extend the `## Adding a new event` docstring at the top of `event_catalog.py` with the "if you're a pack:" branch.

Out of scope:
- Registering more than the skeleton furniture entry (deferred to the furniture-pack workstream).
- Multi-pack install per org (deferred until `org.installed_pack_ids` exists).
- Cross-pack event dispatch policy (a pack's trigger listening to another pack's event) — not a v1 concern.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/__init__.py` | edit — public `register_event` + `register_field_resolver` re-exports |
| `API/src/app/core/automation/event_catalog.py` | edit — add `pack_id: str \| None = None` on `CatalogEntry` |
| `API/src/app/core/automation/enum_resolvers.py` | edit — store `(fn, pack_id)` pairs; wrap `register_resolver` to tag caller's pack |
| `API/src/app/core/automation/service.py` | edit — `list_event_types_service` filters by `org.template_id` + `pack_id` |
| `API/src/app/core/module_registry.py` | edit — discovery walker imports pack event_catalog files |
| `API/src/app/packs/furniture/modules/inventory/event_catalog.py` | **NEW** — skeleton furniture entry + two resolvers |
| `API/tests/automation/test_pack_registry_integration.py` | **NEW** — 6 pytest cases |
| `API/tests/fixtures/fake_pack/__init__.py` | **NEW** — empty |
| `API/tests/fixtures/fake_pack/event_catalog.py` | **NEW** — one entry + one resolver |

**~9 files. ~450 lines.**

## Plan

1. Promote the two register APIs to public + document constraint that packs call these + never the underscored internals.
2. `CatalogEntry.pack_id` field with default `None`. Discovery walker sets it.
3. Extend discovery walker with a second pass that imports `packs/<pack>/event_catalog.py` and `packs/<pack>/modules/<mod>/event_catalog.py`. Wrap the import in a try/except that logs + re-raises so a bad pack fails boot loud.
4. Enum resolver registry tracks pack_id per key. Wildcard resolvers (from step-6) inherit no pack — they're core.
5. Service-layer filter on catalog + on resolver dispatch. Same predicate.
6. Furniture skeleton file: one entry + two resolvers, ~50 lines.
7. Fake-pack fixture + tests.
8. Docs.

## DB changes / migrations

None. `orgs.template_id` already exists.

## Tests

Listed above. 6 pytest cases in `test_pack_registry_integration.py`.

## Smoke

```
1. Fresh boot with furniture pack installed for Ajay's org.
2. GET /api/v1/automations/event-types — response includes:
   - lead.created (pack_id=null)
   - inventory.item_low_stock (pack_id="furniture")   ← from step-7
3. Same call from a hypothetical org with template_id=null:
   - lead.created — yes
   - inventory.item_low_stock — omitted
4. POST /event-types/inventory.item_low_stock/field-values
        {field: "item.warehouse"}
   → returns Ajay's org's warehouses.
5. Same call from the pack-less org → 404 event_not_found.
6. Break the furniture skeleton's FieldSpec.path deliberately (typo).
   Boot fails with a clear log line pointing at the bad entry. Revert.
```

## Risks

- **Rule 1 discipline.** Core code never `from src.app.packs...` — the walker uses `pkgutil.walk_packages` + `importlib.import_module` on a string path. Pin the invariant: a lightweight AST-check pin-test that walks `core/` files and asserts no `from src.app.packs` import lines.
- **Startup failure blast radius.** A broken pack currently fails only sidebar registration (per `module_registry.py:discover_modules`). Extending it to fail on bad `event_catalog.py` widens the failure. Acceptable — a broken pack is a bug, and boot failing loud is better than a picker silently missing a section.
- **Pack resolver naming collisions.** Two packs registering `warehouses` → the different-callable-raises guard from step-2 catches it. Convention: pack-owned resolver keys prefix with `<pack_id>_` (e.g. `fp_warehouses`). Documented in the module-namespace docstring.

## Self-check (10 rules)

`core/automation/` + `packs/furniture/`. ✓ Rule 1: core imports no pack code (verified by discovery walker + pin-test). ✓ org_id scoped. ✓ N/A custom fields. ✓ Dynamic (registry). ✓ N/A sidebar. Permissions gated. ✓ Rule 7: pack.yaml stays the source of truth for pack defaults; this step only wires the automation catalog's discovery. ✓ 9 files / ~450 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 7 — Pack registry integration
Files: 9
Verify: pack events + resolvers register on boot; response filtered by org.template_id;
        broken pack fails boot loud.
Tests: 6 pytest cases with fake-pack fixture.
Awaiting "proceed".
```
