# Step 1 — Backend: registry of overridable standard fields + permission key

**Goal:** Declare in code, per entity, which standard (DB-column) fields are exposed to org-level overrides and which presentational knobs (label, placeholder, help, required, hidden, min/max/step, display order) each one accepts. Register a new permission key `settings.standard_fields.manage`. No DB tables yet — registry is code-only, like the role-template and module registries.
**Track:** Standard Field Overrides
**Status:** Pending
**Depends on:** Phase 1.5 (permissions registry), Phase 1.8 (module registry pattern).

---

## Scope

In-scope:

- A typed registry `StandardFieldDef` declaring every overridable standard field, keyed by `(entity, field_key)`.
- A composable register-function pattern so packs can extend the registry at startup (Rule 1 — `core/` does not import `packs/`; packs call `core.standard_fields.register(...)`).
- Core registers the universal CRM entities: `contact`, `lead`, `walk_in`, `task`, `appointment`, `catalog_item`.
- One new permission key, `settings.standard_fields.manage`, added to the central permissions registry and pre-granted to the `owner` and `admin` role templates.
- A helper `get_overridable_props(entity, field_key) -> set[str]` that returns the subset of knobs allowed for a given field (e.g. `min/max/step` only for numeric types).

Out of scope:

- No DB table yet — Step 2 creates `standard_field_overrides`.
- No HTTP endpoints — Step 3 wires the merge endpoint.
- No pack registrations — furniture pack hooks land alongside Phase 4 / pack installer work, separately.
- No frontend changes.

## The `StandardFieldDef` shape

```python
# api/src/app/core/standard_fields/registry.py

@dataclass(frozen=True)
class StandardFieldDef:
    entity: str               # "contact" | "lead" | "walk_in" | "task" | "appointment" | "catalog_item"
    field_key: str            # matches the DB column / Pydantic schema key 1:1: "budget", "full_name", "expected_close_date", ...
    field_type: Literal[
        "text", "textarea", "email", "tel", "number", "currency",
        "date", "datetime", "select", "multiselect", "tags", "boolean",
    ]                         # presentational type; drives which knobs are overridable
    default_label: str        # the label used when no override row exists
    default_placeholder: str | None
    default_help: str | None
    default_required: bool    # whether the field is required by default (matches current hardcoded behaviour)
    default_min: float | None
    default_max: float | None
    default_step: float | None
    default_display_order: int  # 0-based position in the form
    backend_required: bool    # True if the underlying API/DB enforces NOT NULL — hiding is allowed but the UI warns
    backend_validators: list[str]  # human-readable hints surfaced in the editor ("email format", "must be ≥ 0") — informational, never altered by overrides
    overridable_props: frozenset[str]   # subset of {"label", "placeholder", "help", "required", "hidden", "min", "max", "step", "display_order"}
```

The `overridable_props` set is the contract Step 2 enforces. E.g. for `contact.email` we'd allow `{label, placeholder, help, required, hidden, display_order}` but **not** `min/max/step` (irrelevant for emails) and **not** type-level email-format relaxation (still backend-enforced).

## Initial core registrations

The Step's job is to land the registry plus first-pass entries. Suggested seeds (final list is the implementer's call based on current schemas):

```python
register(StandardFieldDef(
    entity="lead", field_key="budget", field_type="currency",
    default_label="Budget (₹)", default_placeholder="0.00", default_help=None,
    default_required=False, default_min=0.0, default_max=None, default_step=0.01,
    default_display_order=1,
    backend_required=False,
    backend_validators=["must be ≥ 0", "max 12 digits + 2 decimals"],
    overridable_props=frozenset({"label", "placeholder", "help", "required", "hidden", "min", "max", "step", "display_order"}),
))

register(StandardFieldDef(
    entity="contact", field_key="full_name", field_type="text",
    default_label="Full name", default_placeholder="e.g. Asha Reddy", default_help=None,
    default_required=True,
    default_min=None, default_max=255, default_step=None,
    default_display_order=0,
    backend_required=True,
    backend_validators=["max 255 chars"],
    overridable_props=frozenset({"label", "placeholder", "help", "display_order"}),  # required+hidden locked: NOT NULL
))
```

Mirror the rest of the modals listed in the README. Final per-entity list is captured in the step report.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/standard_fields/__init__.py` | created — exposes `register`, `get`, `list_for_entity`, `list_all`, `get_overridable_props`. |
| `api/src/app/core/standard_fields/registry.py` | created — the `StandardFieldDef` dataclass, the in-process dict, the registration functions, and the **core** registrations (one `register(...)` call per overridable standard field across the 6 core entities). |
| `api/src/app/core/permissions/registry.py` | modified — register the new `settings.standard_fields.manage` permission key + add it to the `owner` and `admin` role templates' `permission_keys` lists. |
| `api/src/app/main.py` | modified (small) — import `core.standard_fields` at startup so its module-level `register(...)` calls run. Already the established pattern for module-registry composables. |
| `api/tests/test_standard_field_registry.py` | created — pin the registry against the documented contract (see "Tests" below). |

**5 files. No migration. No router changes yet.**

## Plan

1. Create the `core/standard_fields/` package with the registry module + dataclass + registration functions. Mirror `core/permissions/role_templates.py` for shape consistency.
2. Walk through each of the 12 form modals listed in the parent README and decide which fields are overridable + which knobs each accepts. Land the `register(...)` calls.
3. Add the `settings.standard_fields.manage` key to `core/permissions/registry.py`. Add it to `owner` (via the `ALL_KEYS` sentinel, automatically) and to `admin` (explicit append in the `admin` template's `permission_keys`).
4. Wire startup import in `main.py`.
5. Write `test_standard_field_registry.py` (see below).

## DB changes / migrations

**None.** Registry is code-only.

## Tests

`api/tests/test_standard_field_registry.py`:

- **Coverage check:** asserts at least one overridable field per supported entity (`contact`, `lead`, `walk_in`, `task`, `appointment`, `catalog_item`). Catches accidental deletion.
- **Uniqueness:** `(entity, field_key)` pairs are unique across the registry.
- **NOT NULL safety:** for every `StandardFieldDef` with `backend_required=True`, assert `"required"` is **not** in `overridable_props` AND `"hidden"` is **not** in `overridable_props` *unless* the dev explicitly opted in by documenting a downstream guard. (The Step 4 UI also warns at edit time.)
- **Overridable-props grammar:** `min/max/step` only allowed when `field_type` is one of `{number, currency}`. Tests that none of the text/email/select fields include those keys.
- **Permission key registered:** `settings.standard_fields.manage` is present in the permissions registry after startup.
- **Role template grants:** the `admin` role template (per `tasks/rbac-ownership/step-2-role-templates-auto-seed.md`) includes `settings.standard_fields.manage`. `owner` resolves it via `ALL_KEYS`. `employee` does **not**.

## Smoke

```
docker exec template_api-api-1 pytest tests/test_standard_field_registry.py -v

# Sanity check: registry resolves at startup
docker exec template_api-api-1 python -c "
from src.app.core.standard_fields import list_all
defs = list_all()
print(f'{len(defs)} overridable standard fields registered')
for d in defs[:5]:
    print(f'  {d.entity}.{d.field_key} -> {d.field_type}, knobs={sorted(d.overridable_props)}')
"
```

Expected: ≥ 15 registered defs across the 6 core entities; the first few print with correctly scoped `overridable_props`.

## Risks

- **Field-list drift between registry and live schemas:** if a developer renames `leads.budget` to `leads.amount` without updating the registry, Step 3's merge endpoint would silently drop the override. Mitigation: the test in `test_standard_field_registry.py` (in a follow-on cleanup pass once Step 2 lands) can introspect the SQLAlchemy models for each entity and assert every registered `field_key` corresponds to an actual column. Out of scope for *this* step but flagged.
- **Pack additions arriving later:** Step 1 lands only core fields. When the furniture pack adds an `inventory.qty_on_hand` to a modal it cares about, that registration belongs in the pack's installer code, not here. No code change to this registry beyond keeping `register(...)` callable from outside.
- **Owner grant set surprise:** `owner` resolves keys via `ALL_KEYS` (per `rbac-ownership/step-2-…`), so the new key flows in automatically. `admin` needs an explicit append — easy to forget. Test pins both.

## Rollback

Delete `core/standard_fields/`. Remove the `settings.standard_fields.manage` line from `core/permissions/registry.py` and from the `admin` template. Remove the import from `main.py`. Delete the test file. No DB state to roll back.
