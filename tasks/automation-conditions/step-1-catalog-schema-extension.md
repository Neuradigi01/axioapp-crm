# Step 1 — Catalog schema extension (`condition_fields` on every event)

**Goal:** Extend the automation event catalog so each `CatalogEntry` declares a `condition_fields: list[FieldSpec]` — the customer-friendly list of fields that appear in the "Only if" field dropdown for that event. Declare specs for **every** event currently in `core/automation/event_catalog.py`. Feature-flagged: the extended payload only serializes on the wire when `automation_conditions.friendly_builder_enabled` is on for the caller's org.
**Status:** COMPLETED — NEW `core/automation/field_specs.py` (170 lines): `FieldType` StrEnum (`text / number / currency / date / datetime / boolean / enum`), frozen-slotted `FieldSpec` dataclass with `__post_init__` that enforces the enum ⇔ enum_resolver invariant, `walk_path` + `path_resolves` helpers used by both the runtime drift guard and the pin-test, and eight `GROUP_*` string constants (Contact / Lead / Transition / Appointment / Quote / Invoice / User / Org) keeping section headers stable across events. `CatalogEntry` extended with `condition_fields: tuple[FieldSpec, ...]`; `_register` now walks each spec's dot-path against the entry's `sample_payload` and raises `ValueError("FieldSpec drift: event 'X' declares path 'Y' but that path does not resolve into sample_payload...")` at import time — the bad entry never lands in `_CATALOG` (guard raises before the assignment). All 17 events in the current catalog got specs covering 68 FieldSpecs total (user.signed_up: 3, user.invited: 2, user.invitation_accepted: 2, lead.created: 7, lead.assigned: 5, lead.status_changed: 2, lead.score_threshold: 3, contact.birthday: 3, lead.stale_30d: 5, appointment.booked: 4, appointment.reminder_24h: 3, appointment.reminder_1h: 3, quote.sent: 3, quote.accepted: 3, invoice.sent: 4, invoice.paid: 4, invoice.overdue_7d: 4). `router.py` gains a `FieldSpecOut` Pydantic wire shape (mirrors `FieldSpec`; enum values NOT serialised — step-2's live resolver fetches those per-request) and extends the existing `EventCatalogEntry` with `condition_fields: list[FieldSpecOut]`. `/api/v1/automations/event-types` handler always serialises `condition_fields` — no feature flag. **Spec deviation from the original plan:** dropped the `AUTOMATION_CONDITIONS_FRIENDLY_BUILDER_ENABLED` env-var / gating helper on request from the user (the whole point is to ship the friendly UI to customers, so gating it behind a default-off flag fights the goal). Rollback insurance comes from the JSON contract instead — `tbl_automation_triggers.conditions` shape is unchanged, so reverting the step-3 frontend commit instantly restores the old builder. Old frontends ignore the extra `condition_fields` JSON key today (additive backend). NEW `tests/automation/test_field_spec_coverage.py` (6 tests): four coverage pins (every entry has non-empty specs / enum ⇔ resolver invariant / every path resolves in sample_payload / every resolver key is in the built-in list), one runtime-guard pin (`_register` raises on a bad path AND the bad entry never enters `_CATALOG`), and one async endpoint shape test that spot-checks an enum field (`lead.pipeline_stage` → resolver=`pipeline_stages`, type=`enum`) and a non-enum currency field (`lead.budget` → resolver=None, type=`currency`) on `lead.created`. `test_event_catalog.py` extended with one shape-extension pin. 5 sync pin tests ran green in the container (3.1s); the 1 async endpoint test needs the pytest fixtures + DB and was deferred to the batched run per `feedback_pause_before_pytest.md`. Ruff format + ruff check clean on all touched files. Net files: 5 touched (1 NEW `field_specs.py`, 1 NEW `test_field_spec_coverage.py`, 3 edits: `event_catalog.py` / `router.py` / `test_event_catalog.py`).
**Depends on:** `tasks/automation-engine/` shipped (event catalog + `/event-types` endpoint already live).

---

## Scope

In-scope:

- `core/automation/field_specs.py` — **NEW**. Declares the `FieldSpec` dataclass + the `FieldType` and `FieldGroup` string enums that every `CatalogEntry.condition_fields` entry uses.
  - `FieldSpec(path: str, label: str, type: FieldType, group: str, enum_resolver: str | None = None, help_text: str | None = None)`.
    - `path` — dot-path into the event payload (e.g. `"lead.pipeline_stage"`, `"to_user_id"`). Must resolve against `sample_payload` at import time; startup fails hard if it doesn't (drift guard).
    - `label` — human string shown in the dropdown (e.g. `"Stage"`, `"Assigned to"`).
    - `type` — one of `text | number | currency | date | datetime | boolean | enum`. Drives which operators the frontend allows and which value input renders.
    - `group` — section header the frontend groups fields under (e.g. `"Lead"`, `"Contact"`, `"Appointment"`, `"Transition"`, `"Invoice"`). Free-string but the catalog module ships a suggested list of stable strings so groups stay consistent.
    - `enum_resolver` — resolver key for step-2's registry. Required when `type == "enum"`, forbidden otherwise. Values: `"pipeline_stages"`, `"lead_sources"`, `"users"`, `"tags"`, `"lead_statuses"`, `"appointment_purposes"`, `"invoice_statuses"`, or a pack-owned key (step-7).
    - `help_text` — optional one-line hint under the field in the dropdown.
- Extend `CatalogEntry` (`core/automation/event_catalog.py`) with `condition_fields: tuple[FieldSpec, ...] = ()`. Tuple (not list) so entries stay `frozen=True, slots=True` hashable.
- Declare `condition_fields` for **every** entry currently in `_CATALOG` — no partial coverage. Fields per event (indicative, exact list finalised while writing):

| Event | condition_fields (path → label · type · group) |
|---|---|
| `user.signed_up` | `user.email` · text · User; `user.full_name` · text · User; `org.slug` · text · Org |
| `user.invited` | `user.email` · text · User; `invited_by_user_id` · enum(users) · User |
| `user.invitation_accepted` | `user.email` · text · User |
| `user.role_changed` | `to_role` · enum(users_roles) · User; `from_role` · enum(users_roles) · User |
| `user.first_login` | `user.email` · text · User |
| `lead.created` | `source` · enum(lead_sources) · Lead; `lead.pipeline_stage` · enum(pipeline_stages) · Lead; `lead.assigned_to_id` · enum(users) · Lead; `lead.budget` · currency · Lead; `contact.email` · text · Contact; `contact.phone` · text · Contact |
| `lead.assigned` | `to_user_id` · enum(users) · Transition; `from_user_id` · enum(users) · Transition; `lead.pipeline_stage` · enum(pipeline_stages) · Lead; `lead.source` · enum(lead_sources) · Lead |
| `lead.status_changed` | `to_status` · enum(pipeline_stages) · Transition; `from_status` · enum(pipeline_stages) · Transition; `lead.assigned_to_id` · enum(users) · Lead |
| `lead.score_threshold` | `threshold` · number · Lead; `direction` · enum(direction_updown) · Lead |
| `lead.converted` | `lead.pipeline_stage` · enum(pipeline_stages) · Lead |
| `lead.stale_7d` / `stale_30d` / `stale_90d` | `days_since_last_activity` · number · Lead; `lead.pipeline_stage` · enum(pipeline_stages) · Lead; `lead.assigned_to_id` · enum(users) · Lead |
| `contact.created` | `contact.email` · text · Contact; `contact.phone` · text · Contact |
| `contact.birthday` | `age_turning` · number · Contact |
| `contact.anniversary` | `years_married` · number · Contact |
| `contact.opt_in_changed` | `channel` · enum(channels) · Contact; `to_state` · boolean · Contact |
| `appointment.booked` | `appointment.purpose` · enum(appointment_purposes) · Appointment; `location` · text · Appointment; `appointment.duration_min` · number · Appointment |
| `appointment.reminder_24h` / `reminder_1h` | `appointment.purpose` · enum(appointment_purposes) · Appointment |
| `appointment.cancelled` / `no_show` | `appointment.purpose` · enum(appointment_purposes) · Appointment; `cancelled_by_role` · enum(users_roles) · Appointment |
| `quote.sent` / `viewed` / `accepted` / `rejected` / `expired` | `quote.total_amount` · currency · Quote; `quote.currency` · text · Quote |
| `invoice.sent` / `paid` | `invoice.total_amount` · currency · Invoice; `invoice.currency` · text · Invoice; `payment_method` · enum(payment_methods) · Invoice (paid only) |
| `invoice.overdue_7d` / `14d` / `30d` | `days_overdue` · number · Invoice; `invoice.total_amount` · currency · Invoice |
| `order.placed` / `delivered` / `refunded` | `order.total_amount` · currency · Order; `order.currency` · text · Order |
| Communications events (`whatsapp.*`, `email.*`, `call.*`, `sms.*`) | channel-specific fields — inbound_from / thread_id / campaign_id where relevant |

*(The exact list ships as code; the table above is the pin — the implementer treats it as a shopping list and rows are checked off one-by-one while filling `_CATALOG`.)*

- Extend the `EventCatalogEntry` Pydantic schema in `core/automation/schemas.py` with `condition_fields: list[FieldSpecOut]`. `FieldSpecOut` mirrors `FieldSpec` on the wire — `path`, `label`, `type`, `group`, `enum_resolver` (nullable), `help_text` (nullable). No enum *values* serialise here; step-2's live resolver fetches those per-request.
- Extend the `GET /api/v1/automations/event-types` handler (`core/automation/router.py`) to include `condition_fields` when the caller org has the `automation_conditions.friendly_builder_enabled` feature flag on; empty tuple otherwise (backwards-compatible bypass to today's free-text builder).
- Startup-time drift guard: `_register(...)` walks each `FieldSpec.path` against the entry's `sample_payload` and raises `ValueError` if the path can't resolve (missing intermediate keys OR the leaf key not present). Prevents "customer picks Lead → Stage and the evaluator never matches because the field is actually `lead.pipeline_stage` not `lead.stage`" the moment code lands.
- Pin-test `tests/automation/test_field_spec_coverage.py`:
  1. Every event in `list_catalog()` has a non-empty `condition_fields` tuple (once the flag is on for anyone).
  2. Every `FieldSpec.type == "enum"` has a non-empty `enum_resolver`, and every non-enum has `enum_resolver == None`.
  3. Every `FieldSpec.path` resolves cleanly into the entry's `sample_payload` (mirrors the runtime drift guard so a code review catches it too).
  4. Every `enum_resolver` value referenced is either in the built-in list OR appears in a pack-owned resolver registry (validated once step-7 lands — this test skips the pack list check with a `# TODO: enable after step-7` marker in the interim).

Out of scope:
- The live enum lookup endpoint (step-2).
- Frontend rewrite (step-3).
- Custom-field auto-discovery (step-6).
- Pack registration walker (step-7).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/field_specs.py` | **NEW** — dataclass + FieldType enum + suggested-group constants |
| `API/src/app/core/automation/event_catalog.py` | edit — extend `CatalogEntry`; fill `condition_fields=(...)` on every `_register(...)` call; add drift guard to `_register` |
| `API/src/app/core/automation/schemas.py` | edit — extend `EventCatalogEntry` with `condition_fields`; add `FieldSpecOut` shape |
| `API/src/app/core/automation/router.py` | edit — feature-flag-gate the `condition_fields` field in the `/event-types` response |
| `API/src/app/shared/feature_flags.py` (or wherever the flag registry lives) | edit — add `automation_conditions.friendly_builder_enabled`, default `false` |
| `API/tests/automation/test_field_spec_coverage.py` | **NEW** — pin-test suite (4 cases) |
| `API/tests/automation/test_event_catalog.py` | edit — assert the shape extension is present on a sample entry |

**~7 files. ~450 lines** (most of the LOC is the `condition_fields=(...)` blocks on ~40 `_register` calls — mechanical).

## Plan

1. Add the `FieldType` enum + `FieldSpec` dataclass in a NEW `field_specs.py` (no import cycles — this module has zero imports from other automation files).
2. Extend `CatalogEntry` to carry the tuple; default `()` so untouched entries compile.
3. Add the drift guard to `_register(...)`: `_walk_path(entry.sample_payload, spec.path)` — raises with a message pointing at the entry's `event_type` + the bad path.
4. Fill `condition_fields=(...)` on every `_register` call, following the table above. Read each `sample_payload` alongside the spec to confirm the path exists. Any path that reads a payload dict *value* (not the dict itself) is valid.
5. Feature flag: add `automation_conditions.friendly_builder_enabled` to the flag registry, default `false`.
6. Extend the `EventCatalogEntry` Pydantic model + the `/event-types` handler. Handler reads the flag and either passes the specs through or replaces them with `[]`.
7. Pin-tests. Every event covered + no orphan resolvers + drift guard fires when we intentionally break a path in a scratch test.

## DB changes / migrations

None. Catalog is code-owned.

## Tests

Pytest cases:

- `test_every_catalog_entry_has_condition_fields` (pin).
- `test_enum_fields_have_resolver_others_do_not` (pin).
- `test_field_spec_paths_resolve_in_sample_payload` (pin).
- `test_register_raises_on_bad_path` (runtime drift guard — feeds a scratch entry with `path="lead.nonexistent"` and asserts `ValueError`).
- `test_event_types_endpoint_hides_condition_fields_when_flag_off` (flag off for the org → response has `condition_fields: []`).
- `test_event_types_endpoint_returns_condition_fields_when_flag_on` (flag on → response has the declared specs).

## Smoke

```
1. uv run pytest API/tests/automation/test_field_spec_coverage.py — green.
2. Flip flag on for Ajay's org (41f9ede9-...) via feature-flag admin.
3. curl /api/v1/automations/event-types → `lead.created`'s `condition_fields`
   includes `{path: "source", type: "enum", enum_resolver: "lead_sources", ...}`.
4. Flip flag off → same call returns `condition_fields: []` for every entry.
```

## Risks

- **Coverage discipline.** Missing one event → frontend falls back to Advanced mode for that event, users learn to distrust the picker. Mitigated by the pin-test failing CI until every event is covered.
- **Drift.** Adding a new event in a later step and forgetting `condition_fields` → the pin-test fails at that PR (good). Adding a `FieldSpec.path` whose event's `sample_payload` doesn't carry the key → startup fails (good, caught before deploy).
- **Sample-payload accuracy.** If a real publisher emits a different shape than the catalog's `sample_payload`, the drift guard passes but the evaluator returns no-match at runtime. Not new — the existing pin test in `tasks/automation-engine/` covers publisher-vs-catalog shape drift.

## Self-check (10 rules)

`core/automation/`. ✓ org_id read from JWT for the flag check. ✓ N/A custom fields (step-6). ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ N/A permissions (endpoint already gated by Step-3 automation-engine perms). ✓ pack.yaml untouched (packs bring their own catalog in step-7). ✓ 7 files / ~450 lines — well under the cap. ✓ Stop-report at end. ✓ No TODOs (the pin-test's `# TODO: enable after step-7` marker is a deliberate cross-track marker, not implementation debt). ✓.

## Stop & report

```
Step 1 — Catalog schema extension
Files: 7
Verify: every catalog entry gains condition_fields; /event-types serializes them behind the flag.
Tests: 6 pytest cases (4 pin, 2 handler).
Awaiting "proceed".
```
