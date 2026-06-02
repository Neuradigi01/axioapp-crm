# Code Update — Shared-Code Refactor Track

A 20-step refactor track that consolidates duplicated code in the FurnitureCRM backend (`api/src/app/`) and frontend (`app/src/app/features/user/`) into shared utilities.

Source: codebase scan performed 2026-06-02. All findings reflect duplication that **already exists** in the repo — this is not a forward-looking architecture proposal.

**Total potential reduction: ~4,000 LOC** across ~50 files.

---

## Execution discipline

Same rules as the 76-step build plan:
1. **Announce:** "Starting Step N: <Title>."
2. Plan briefly (5–10 bullets).
3. Implement strictly within scope.
4. Migrations: write Alembic up + down if DB touched.
5. Tests: cover the shared utility AND at least one consumer.
6. Self-check against the 10 rules.
7. Stop and report — **wait for "proceed"** before the next step. Never batch.

---

## Step index — in suggested execution order

### Foundations (backend helpers — pure utility, no schema change)
- [Step 1 — Generic PaginatedResponse[T] schema](step-1-paginated-response-schema.md)
- [Step 2 — get_or_404 helper](step-2-get-or-404-helper.md)
- [Step 3 — apply_offset_pagination helper](step-3-pagination-query-helper.md)
- [Step 4 — ORMModel base Pydantic class](step-4-orm-model-base.md)
- [Step 5 — TimestampedOrgScopedOut mixin](step-5-timestamped-mixin.md)

### Audit & validation engines
- [Step 6 — log_entity_change audit wrapper](step-6-audit-log-wrapper.md)
- [Step 7 — Generic _snapshot helper](step-7-audit-snapshot-helper.md)
- [Step 8 — Shared custom-data validation engine](step-8-custom-fields-validation.md)
- [Step 9 — Shared bulk-action schemas](step-9-bulk-action-schemas.md)
- [Step 10 — Field-type coercion switch](step-10-field-coercion-switch.md)

### Frontend foundation
- [Step 11 — buildHttpParams utility](step-11-http-params-builder.md)
- [Step 12 — BaseApiService<T>](step-12-base-api-service.md)
- [Step 13 — ListPageState<T> service](step-13-list-page-state.md)
- [Step 14 — BaseFormModalComponent<T>](step-14-base-form-modal.md)
- [Step 15 — Shared BulkAction config + modal state](step-15-bulk-action-config.md)

### Frontend polish
- [Step 16 — Reuse validatorsForField() everywhere](step-16-reuse-validators-for-field.md)
- [Step 17 — Tailwind cluster components (badge, button-group, icon-button)](step-17-tailwind-cluster-components.md)
- [Step 18 — Consolidate exportCsv param building](step-18-export-csv-consolidation.md)
- [Step 19 — Typed lucide-icon enum](step-19-typed-lucide-icons.md)

### Cross-cutting
- [Step 20 — FE ↔ BE type codegen](step-20-fe-be-type-codegen.md)

---

## Self-check before starting any step

- [ ] Step touches ≤ 10 files / ≤ 400 LOC. If not, split it.
- [ ] No `/core` → `/packs` imports introduced.
- [ ] Every query still filters by `org_id`; RLS unchanged.
- [ ] No hardcoded furniture defaults in core utilities.
- [ ] No TODOs, no commented-out code.
- [ ] Tests cover the new utility AND at least one consumer.
- [ ] Backend: `uv run pytest` clean; if migration, verify up + down via `API\docker-helper.cmd`.
- [ ] Frontend: `ng build` + browser smoke against Ajay's Workspace (`41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com`).
- [ ] Step report ends with "Awaiting your 'proceed'".
