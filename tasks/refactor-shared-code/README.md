# Shared-Code Refactor Backlog

A prioritized list of duplicated code in the FurnitureCRM backend (`api/src/app/`) and frontend (`app/src/app/features/user/`) that can be extracted into shared utilities.

Source: codebase scan performed 2026-06-02. All findings reflect duplication that **already exists** in the repo — this is not a forward-looking architecture proposal.

**Total potential reduction: ~4,000 LOC** across ~50 files.

---

## How to use this document

Each item is a self-contained, individually verifiable refactor — same execution discipline as the 76-step build plan (announce → plan → implement → migrate → test → self-check → stop).

- Items are grouped by **area** (backend / frontend / cross-cutting), then by **priority** (Critical → High → Medium → Quality).
- The **Suggested execution order** at the bottom sequences items so each refactor builds on its predecessors.
- Don't bundle items unless the order table groups them — small, reviewable steps win.

---

## Backend (`api/src/app/`)

### Critical

#### B1. Generic `PaginatedResponse[T]` schema
- **Problem:** 16+ list endpoints each define their own `ListResponse` with identical `items / total / page / size` shape.
- **Examples:**
  - `app/core/contacts/schemas.py:98-102`
  - `app/core/leads/schemas.py:135-152`
  - `app/core/tasks/schemas.py`, `core/calls/schemas.py`, `core/campaigns/schemas.py`, `core/catalog/schemas.py`, `core/appointments/schemas.py`, etc.
- **Extract to:** `app/shared/schemas/pagination.py` — `PaginatedResponse[T](BaseModel)` generic.
- **LOC saved:** ~960

#### B2. `get_or_404(session, model, id, entity_name)` helper
- **Problem:** 15+ inlined `if row is None: raise HTTPException(404, ...)` blocks across every service.
- **Examples:**
  - `app/core/contacts/service.py:258-262`
  - `app/core/leads/service.py:362-366`
  - `app/core/appointments/service.py:362-367`
  - `app/packs/furniture/modules/inventory/service.py:71-74`
  - `app/packs/furniture/modules/custom_orders/service.py:93-97`
  - Also in: calls, campaigns, catalog, conversations, billing, walk_ins, tasks, reviews
- **Extract to:** `app/shared/db/queries.py::get_or_404(...)`.
- **LOC saved:** ~120

#### B3. `apply_offset_pagination(stmt, page, size)` helper
- **Problem:** Same `.offset((page-1)*size).limit(size)` + count pattern in 11+ services.
- **Examples:**
  - `app/core/contacts/service.py:385-388`
  - `app/core/leads/service.py`, `core/tasks/service.py`, `core/appointments/service.py`, `core/campaigns/service.py`, `core/calls/service.py`
- **Extract to:** `app/shared/db/pagination.py::apply_offset_pagination(stmt, page, size)`.
- **LOC saved:** ~200

#### B4. Custom-data validation engine
- **Problem:** `_load_field_defs()`, `_coerce_value()`, `_validate_custom_data()` duplicated near-verbatim in 5 services.
- **Examples:**
  - `app/core/contacts/service.py:68-193`
  - `app/core/leads/service.py:126-235`
  - `app/core/appointments/service.py:85-175`
  - `app/core/catalog/service.py`
  - `app/core/walk_ins/service.py`
- **Extract to:** `app/shared/custom_fields/validation.py`.
- **LOC saved:** ~200

### High value

#### B5. `log_entity_change(action, entity_type, entity_id, before, after)` audit wrapper
- **Problem:** 126 inlined `audit.log("entity.created/updated/deleted", entity_type=..., entity_id=..., after=_snapshot(...))` calls.
- **Examples:**
  - `app/core/contacts/service.py:243-248, 287-292, 310-315`
  - `app/core/leads/service.py:347-352, 396-402, 417-422`
  - `app/core/appointments/service.py:333-338, 436-442, 473-479`
- **Extract to:** `app/shared/audit/helpers.py::log_entity_change(...)`.
- **LOC saved:** ~150

#### B6. Generic `_snapshot(entity)` builder
- **Problem:** 7 hand-rolled snapshot helpers with the same fields (id, dates, org_id, custom_data, audit fields).
- **Examples:**
  - `app/core/contacts/service.py:49-65`
  - `app/core/leads/service.py:96-118`
  - `app/core/appointments/service.py:67-79`
  - `core/catalog/`, `core/campaigns/`, `core/tasks/`, `core/walk_ins/`
- **Extract to:** `app/shared/audit/snapshots.py` — generic helper + entity-specific overrides.
- **LOC saved:** ~100

#### B7. `ORMModel` base Pydantic class
- **Problem:** `model_config = ConfigDict(from_attributes=True)` repeated 53 times.
- **Extract to:** `app/shared/schemas/base.py::ORMModel(BaseModel)` with pre-configured `ConfigDict`.
- **LOC saved:** ~30

#### B8. `TimestampedOrgScopedOut` mixin
- **Problem:** `org_id: UUID`, `created_at: datetime`, `updated_at: datetime` redefined in 98 output schemas.
- **Extract to:** `app/shared/schemas/base.py::TimestampedOrgScopedOut` mixin.
- **LOC saved:** ~70

### Medium value

#### B9. Shared bulk-action schemas
- **Problem:** Identical `BulkReassign`, `BulkDelete`, `BulkAddTag` schemas in contacts/leads/tasks.
- **Examples:**
  - `app/core/contacts/schemas.py:118-147`
  - `app/core/leads/schemas.py:167-184`
- **Extract to:** `app/shared/schemas/bulk_actions.py`.
- **LOC saved:** ~50

#### B10. Field-type coercion switch
- **Problem:** Identical `if field_type in (text, phone, email, select): ...` chain in 5 services.
- **Extract to:** `app/shared/custom_fields/coercion.py`.
- **LOC saved:** ~80

**Backend subtotal: ~1,960 LOC**

---

## Frontend (`app/src/app/features/user/`)

### Critical

#### F1. `BaseApiService<T>`
- **Problem:** 18 API services each reimplement `list / get / create / update / delete / bulkDelete / bulkReassign`. Each service is ~100–150 LOC of boilerplate.
- **Examples:** `contacts/contacts-api.service.ts`, `leads/leads-api.service.ts`, `tasks/tasks-api.service.ts`, `walk-ins/walk-ins-api.service.ts`, `appointments/appointments-api.service.ts`, `catalog/catalog-api.service.ts`, etc. (18 total).
- **Extract to:** `core/shared/services/base-api.service.ts` — abstract `BaseApiService<T, Q>` with subclasses overriding `basePath` + domain-specific methods.
- **LOC saved:** ~600

#### F2. `buildHttpParams(query)` utility
- **Problem:** 18 services hand-build `HttpParams` with the same conditional `if (query.x) params = params.set('x', ...)` chain.
- **Examples:**
  - `contacts/contacts-api.service.ts:146-165, 240-259`
  - `leads/leads-api.service.ts:292-323 (buildParams)`
  - `tasks/tasks-api.service.ts:77-90 (toParams)`
  - `walk-ins/walk-ins-api.service.ts:83-94`
- **Extract to:** `core/shared/services/query-builder.ts::buildHttpParams(query)`.
- **LOC saved:** ~300

### High value

#### F3. `ListPageState<T>` service
- **Problem:** Pagination, sort/filter, selection, bulk-modal signals duplicated across 5+ list pages.
- **Examples:**
  - `contacts/contacts-list.page.ts:71-80, 94-96, 139-143, 147-170`
  - `leads/leads.page.ts:151-180+`
  - `tasks/tasks.page.ts:94-99, 108-116, 137-139`
  - `walk-ins/walk-ins.page.ts`, `appointments/appointments.page.ts`
- **Signals duplicated:** `items / loading / loadError / total / page / pageSize / selectedIds / selectedCount / allOnPageSelected / bulkActions / bulkModal / bulkSubmitting / bulkError / totalPages`.
- **Extract to:** `core/shared/services/list-page.service.ts` — generic `ListPageState<T>`.
- **LOC saved:** ~200 (folds in F5)

#### F4. `BaseFormModalComponent<T>`
- **Problem:** Every entity modal repeats form group + field-refresh + submit-error signals.
- **Examples:**
  - `contacts/contact-form-modal.component.ts:55-180+`
  - `leads/lead-form-modal.component.ts:58-150+`
  - `tasks/task-form-modal.component.ts`
  - `walk-ins/register-walkin-modal.component.ts`
  - `appointments/book-appointment-modal.component.ts`
- **Pattern duplicated:** Input/Output signals for `entity / submitting / submitError`, FormBuilder group construction, `refreshStdFields() + applyStandardValidators()`, `fieldsLoading / fieldsError / fields` signals, save-emit tuple.
- **Extract to:** `core/shared/components/base-form-modal.component.ts` — abstract `<T>` with lifecycle hooks.
- **LOC saved:** ~250

### Medium value

#### F5. Shared `BulkAction[]` config + modal state
- **Problem:** Same `bulkActions` array (reassign / delete / add tag) + `bulkModal / bulkSubmitting / bulkError` signals in every list page.
- **Folds into F3.**
- **LOC saved:** ~80

#### F6. Reuse `validatorsForField()` everywhere
- **Problem:** `shared/dynamic-form/validators.ts:11-61` already exists, but list-form modals hardcode `Validators.email / Validators.required / Validators.maxLength(32)` instead.
- **Examples:**
  - `contacts/contact-form-modal.component.ts:122-129, 160-189`
  - `leads/lead-form-modal.component.ts` (parallel validators)
  - `tasks/task-form-modal.component.ts`, `appointments/book-appointment-modal.component.ts`
- **Action:** Replace hardcoded validators with `validatorsForField()` calls.
- **LOC saved:** ~50

#### F7. Tailwind cluster components
- **Problem:** ~357 occurrences of the same long classlists (`inline-flex items-center px-3 py-1.5 rounded-md ...`, `px-4 py-2 border rounded ...`, `text-sm text-gray-600 gap-2`) across 80+ files.
- **Extract to:** `core/shared/components/` — `<app-badge>`, `<app-button-group>`, `<app-icon-button>`.
- **LOC saved:** ~150

#### F8. Consolidate `exportCsv` param building
- **Problem:** Export methods copy `list()` params then strip pagination; one missed key breaks export.
- **Examples:**
  - `contacts/contacts-api.service.ts:240-259`
  - `leads/leads-api.service.ts:169-180`
- **Folds into F2.**
- **LOC saved:** ~40

### Quality (no LOC saved, prevents bugs)

#### F9. Typed lucide-icon enum
- **Problem:** `app.config.ts:103-171` defines 62 icons via `LucideAngularModule.pick()`. If a template adds `[lucideIcon]="'new-icon'"` without updating the registry, it silently fails at runtime and breaks every click handler later in the template (per existing memory note).
- **Action:** Create `core/shared/icons.ts` enum of allowed icons; re-export from `app.config.ts`. Optional lint rule to catch literal icon names outside the enum.
- **Benefit:** Compile-time safety; prevents ~10 runtime bugs / quarter.

**Frontend subtotal: ~1,670 LOC**

---

## Cross-cutting

#### X1. FE ↔ BE type codegen
- **Problem:** Every Pydantic response schema has a hand-maintained TS twin. When the backend changes, the FE interface must be manually updated — no synchronization, silent drift.
- **Examples:**
  - `ContactListItem` (FE) ↔ `ContactListResponse` (BE)
  - `Lead` (FE) ↔ `Lead` (BE)
  - `TaskListFilters` (FE) ↔ BE equivalent
  - All custom-field types, all response envelopes
- **Options:**
  1. OpenAPI → `openapi-typescript` (lowest effort, generated client + types).
  2. Custom Pydantic → TypeScript generator emitting to `app/src/app/features/user/core/shared/api-types/`.
- **LOC saved:** ~400 + ongoing drift prevention.

---

## Suggested execution order

| # | Item | Why this order |
|---|------|---------------|
| 1 | **B1** `PaginatedResponse[T]` | Touches almost every list endpoint — do before extracting B3. |
| 2 | **B2** `get_or_404` + **B3** `apply_offset_pagination` | Pure helpers, no schema migration, immediate use. |
| 3 | **B7** `ORMModel` + **B8** `TimestampedOrgScopedOut` | Foundation other schemas depend on. |
| 4 | **B5** audit wrapper + **B6** snapshot helper | Reduces noise in every service before refactoring them. |
| 5 | **B4** custom-fields validation engine | Bigger surgery — do after the helpers above are in place. |
| 6 | **F2** `buildHttpParams` → **F1** `BaseApiService<T>` | FE foundation; unblocks list-page refactor. |
| 7 | **F3** `ListPageState<T>` + **F4** `BaseFormModalComponent<T>` | Largest FE win, builds on F1/F2. |
| 8 | **X1** type codegen | Best done after FE shape stabilises around `BaseApiService<T>`. |
| 9 | **Polish:** B9, B10, F5, F6, F7, F8, F9 | Low-risk cleanups. |

---

## Self-check before starting any item

For each refactor, confirm:

- [ ] Step touches ≤ 10 files / ≤ 400 LOC. If not, split it.
- [ ] No `/core` → `/packs` imports introduced.
- [ ] Every query still filters by `org_id`; RLS unchanged.
- [ ] No hardcoded furniture defaults in core utilities.
- [ ] No TODOs, no commented-out code, no "I'll fix it later".
- [ ] Tests cover the new shared utility AND at least one consumer.
- [ ] Backend: `uv run pytest` + `uv run alembic upgrade head` clean.
- [ ] Frontend: `ng build` + browser smoke against Ajay's Workspace clean.
- [ ] Step report ends with "Awaiting your 'proceed'" — never batch.
