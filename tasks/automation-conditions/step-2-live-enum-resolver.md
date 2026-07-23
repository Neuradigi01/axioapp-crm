# Step 2 — Live enum resolver + registry

**Goal:** Serve the value dropdown for every `enum` field. Introduce a resolver registry + a lookup endpoint that returns the caller org's live options for a given `enum_resolver` key. Core ships the built-in resolvers (`pipeline_stages`, `lead_sources`, `users`, `tags`, `lead_statuses`, `appointment_purposes`, `invoice_statuses`, `payment_methods`, `direction_updown`, `users_roles`, `channels`). Pack-owned resolvers plug into the same registry via step-7.
**Status:** Pending.
**Depends on:** Step 1 (`FieldSpec.enum_resolver` shape locked; feature flag exists).

---

## Scope

In-scope:

- `core/automation/enum_resolvers.py` — **NEW**. Public API:
  - `EnumOption` dataclass — `value: str | int | bool`, `label: str`. Serialised on the wire as `{value, label}` pairs.
  - `EnumResolver` protocol — `async def __call__(db: AsyncSession, org_id: UUID) -> list[EnumOption]`. Pure lookup — no request context, no user identity. RLS is applied via the session's tenant context; the resolver itself never filters by `user_id`.
  - `register_resolver(key: str, fn: EnumResolver) -> None` — idempotent (re-registering same key with same callable is a no-op; re-registering with a *different* callable raises `RuntimeError` at import time — catches accidental key collisions between core and a pack).
  - `get_resolver(key: str) -> EnumResolver | None` — returns `None` when the key isn't registered so the endpoint can 404 cleanly.
  - `list_registered_keys() -> list[str]` — used by the step-1 pin-test to validate every `FieldSpec.enum_resolver` references a real key.
- Built-in resolvers implemented in the same file (or a `resolvers/` sub-package if it grows past ~200 lines — the layered-architecture pin-test permits one file per module, but a package works if `data_access.py` is separate):

| Resolver key | Query |
|---|---|
| `pipeline_stages` | `SELECT key, name FROM tbl_pipeline_stages WHERE org_id = :org_id AND pipeline_key = 'leads' ORDER BY display_order` |
| `lead_sources` | `SELECT key, name FROM tbl_lead_sources WHERE org_id = :org_id ORDER BY display_order` |
| `users` | `SELECT id, full_name FROM tbl_users WHERE org_id = :org_id AND is_active = true ORDER BY full_name` |
| `tags` | `SELECT id, name FROM tbl_tags WHERE org_id = :org_id ORDER BY name` |
| `lead_statuses` | Static — `[active, dormant, unqualified, converted]` — same for every org, but flows through the registry for uniformity |
| `appointment_purposes` | Static — reads from the `AppointmentPurpose` string enum shipped in `core/appointments/models.py` |
| `invoice_statuses` | Static — reads from `InvoiceStatus` enum |
| `payment_methods` | Static — reads from `PaymentMethod` enum |
| `direction_updown` | Static — `[{value: "up", label: "Crossed up"}, {value: "down", label: "Crossed down"}]` |
| `users_roles` | `SELECT role_key, role_name FROM tbl_roles WHERE org_id = :org_id ORDER BY role_name` |
| `channels` | Static from `ConversationChannel` enum — `[email, whatsapp, sms, voice]` |

Static resolvers are trivial helper functions — no DB call — but still registered so the frontend never treats them specially.

- Registry population: import `core/automation/enum_resolvers` from `core/automation/__init__.py` at module load so every built-in registers before `event_catalog`'s pin-test walks them.
- `POST /api/v1/automations/event-types/{event_type}/field-values` endpoint (added to `core/automation/router.py`):
  - Body: `{field: str}` — the `FieldSpec.path` the customer just picked in the field dropdown.
  - Server looks up the catalog entry for `event_type`, finds the matching `FieldSpec` for `field`, reads its `enum_resolver`, dispatches through the registry, returns the org's options.
  - Response: `list[EnumOptionOut]` — `{value, label}`.
  - Errors:
    - Event not in catalog → `404 event_not_found`.
    - Field not in that event's `condition_fields` → `404 field_not_found`.
    - Field is not an enum (`type != "enum"` in the spec) → `422 field_not_enum`.
    - Resolver key not registered → `500 resolver_not_registered` (this is a code bug — pin test should catch it before deploy).
    - Resolver returns 0 rows → **200 with `[]`**, not an error. Frontend renders the "no stages configured" hint.
  - Auth: `require_permissions(PERM_READ)` — same permission as `/event-types` (any user who can view automations can peek at the value pool).
  - Feature-flag guarded — endpoint returns `404 friendly_builder_disabled` when the flag is off for the caller org (keeps the URL surface stable but off-by-default).
  - **Rate limit** — the frontend can call this once per field selection while the customer is authoring; a heavy authoring session might fire 5-10 lookups. Reuse the existing `core/security/rate_limiter.py` middleware with a lenient per-user cap (60/min) to defang a scripted enumeration.
  - **Cache** — `Cache-Control: private, max-age=60`. The frontend also caches in-session (step-3), but the header helps repeat lookups across editor tabs.
- Route the endpoint through the layered convention: router → new `list_field_values_service(...)` → resolver call. Service is the only layer that touches the resolver registry (per rule 3 of the layered architecture pin-test, DAL is for SQL only; the registry sits in `enum_resolvers.py`, not in `data_access.py`).

Out of scope:
- Custom-field-owned resolvers (step-6 introduces `custom_field_options:<entity>:<field_key>` keys).
- Pack-owned resolvers (step-7 registers `fp_warehouses` etc.).
- Frontend consumption (step-3).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/enum_resolvers.py` | **NEW** — protocol, registry, built-ins |
| `API/src/app/core/automation/__init__.py` | edit — import `enum_resolvers` at load so built-ins register |
| `API/src/app/core/automation/service.py` | edit — add `list_field_values_service(db, org_id, event_type, field)` |
| `API/src/app/core/automation/router.py` | edit — add `POST /event-types/{event_type}/field-values` endpoint |
| `API/src/app/core/automation/schemas.py` | edit — add `FieldValuesRequest` + `EnumOptionOut` |
| `API/src/app/core/automation/exceptions.py` | edit — add `FieldNotFound`, `FieldNotEnum`, `ResolverNotRegistered` |
| `API/tests/automation/test_enum_resolvers.py` | **NEW** — resolver registry + endpoint behaviour |

**~7 files. ~500 lines** (most of the LOC is the built-in resolvers + a full test matrix).

## Plan

1. Registry first — `EnumOption`, `EnumResolver` protocol, `_REGISTRY` dict, `register_resolver` with the same-callable idempotency + different-callable-raises guard. Copy the `core.conversations.registry` pattern (rule alignment with existing registries).
2. Built-in resolvers — one function per key. DB-backed ones write minimal SQL through the existing DAL patterns for each domain (e.g. `pipelines.data_access.list_stages_for_pipeline_key(db, org_id, "leads")`). Prefer existing DAL functions to inlining SQL — keeps the pin-test happy.
3. Static resolvers — pure list-returning functions.
4. Auto-register at module import — module-level `register_resolver("pipeline_stages", _resolve_pipeline_stages)` calls at file bottom.
5. Import `enum_resolvers` from `core/automation/__init__.py` so `list_registered_keys()` is populated by the time the step-1 pin-test runs.
6. Service: `list_field_values_service(db, org_id, event_type, field)` — resolves catalog entry → finds field spec → validates `type == "enum"` → dispatches → returns options. Raises the four exceptions above.
7. Router: thin — parses body, calls service, wraps exceptions to HTTP status. Feature flag check reads from the same helper step-1 introduced.
8. Rate limit + Cache-Control header on the response.
9. Tests: 12 pytest cases (below).

## DB changes / migrations

None — every resolver reads existing tables.

## Tests

Pytest cases:

- `test_register_resolver_is_idempotent` — same key + same callable → no-op.
- `test_register_resolver_conflicts_on_different_callable` — same key + different callable → `RuntimeError`.
- `test_pipeline_stages_resolver_returns_caller_org_stages_only` — seed two orgs with distinct stages, RLS isolates.
- `test_lead_sources_resolver_returns_display_order`.
- `test_users_resolver_excludes_inactive`.
- `test_static_direction_updown_resolver_returns_two_options`.
- `test_field_values_endpoint_returns_enum_options` — happy path for `lead.created` / `source`.
- `test_field_values_endpoint_404_when_event_unknown`.
- `test_field_values_endpoint_404_when_field_not_in_spec`.
- `test_field_values_endpoint_422_when_field_not_enum` — pick a `text`-type field.
- `test_field_values_endpoint_200_empty_when_org_has_no_stages` — fresh org, no `tbl_pipeline_stages` rows → `[]`.
- `test_field_values_endpoint_404_when_flag_off` — feature flag disabled → endpoint returns `404 friendly_builder_disabled`.

## Smoke

```
1. uv run pytest API/tests/automation/test_enum_resolvers.py — green.
2. Flag on for Ajay's org.
3. curl -X POST /api/v1/automations/event-types/lead.created/field-values
        -d '{"field": "source"}'
   → [{"value": "widget", "label": "Widget"}, {"value": "google_ads", "label": "Google Ads"}, ...]
4. Same call with {"field": "lead.pipeline_stage"}
   → the org's actual stages, deterministic display_order.
5. Same call with {"field": "contact.email"} → 422 field_not_enum.
6. Same call for a non-existent event → 404 event_not_found.
7. Same call with flag off → 404 friendly_builder_disabled.
```

## Risks

- **Resolver return-type drift.** A resolver that returns strings instead of `EnumOption` dataclasses breaks the endpoint at runtime. Enforce by a `runtime_checkable Protocol` + a pytest that walks every registered resolver on a fixture-populated DB and asserts the return type. Runs in <1s so it stays in the fast suite.
- **N+1 risk.** The endpoint fires per-field; the frontend should cache in-session (step-3 mandates this). A pathological authoring session that repeats the same field 100 times still shouldn't tank the DB — the rate limiter caps it at 60/min per user.
- **Cross-tenant leak.** RLS + the `org_id` filter in every DB query. Two-org fixture test locks this in.
- **Sensitive data via the picker.** `users` resolver returns `full_name` — that's already visible everywhere else in the app the user has permissions to see. Not a leak.

## Self-check (10 rules)

`core/automation/`. ✓ org_id scoped on every resolver + endpoint. ✓ N/A custom fields (step-6). ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ Permission gated (`PERM_READ`). ✓ pack.yaml untouched (pack resolvers register themselves in step-7). ✓ 7 files / ~500 lines — under cap. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 2 — Live enum resolver + registry
Files: 7
Verify: value dropdown for every enum field returns the caller org's live options.
Tests: 12 pytest cases.
Awaiting "proceed".
```
