# Step 7 — Pack registry integration (v1)

**Goal:** Extend the module-registry discovery walker so it also imports each pack's `event_catalog.py`. Packs push their `CatalogEntry` rows + `EnumResolver` implementations into the same registries core populates in steps 1 + 2. `GET /automations/event-types` filters by the caller org's `template_id` — an org sees core events + only-its-installed-pack events. Rule 1 preserved (core never imports packs; discovery is by convention).
**Status:** Pending (v1 — the whole promise "works across every module and every pack" depends on this).
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
