# Step 1 — Templates schema and models

**Goal:** Land the five new tables (`tbl_message_templates` + 4 children) with RLS, SQLAlchemy models, Pydantic schemas, and the per-channel enums. No service, no router, no UI yet.
**Status:** Pending
**Depends on:** Existing `tbl_organizations`, `tbl_users`, `tbl_files`. Reuses `ConversationChannel` enum from `core/conversations/models.py`.

---

## Scope

In-scope:
- Alembic migration creating five tables:
  - `tbl_message_templates` — id, org_id, channel, name, category (`marketing|transactional|service`), language (default `en`), body_text, subject (nullable; email only), preview_text (nullable; email only), variables JSONB, internal_status enum, external_status enum (default `n_a`), external_provider_id (nullable text — Meta template id / DLT id), current_version int default 1, created_by_user_id, updated_by_user_id, timestamps. Unique `(org_id, lower(name), channel)`.
  - `tbl_message_template_versions` — id, template_id (CASCADE), version int, body_text, subject, variables JSONB, changed_by_user_id, changed_at, change_note text. Unique `(template_id, version)`.
  - `tbl_message_template_reviews` — id, template_id (CASCADE), version int, reviewer_user_id, action enum (`submit|approve|reject|request_changes|publish|archive`), note text, created_at.
  - `tbl_message_template_assets` — id, template_id (CASCADE), file_id (FK `tbl_files`, RESTRICT), kind enum (`header_image|inline|attachment`), created_at.
  - `tbl_message_template_test_sends` — id, template_id (CASCADE), version int, sent_to text, channel, sent_by_user_id, sent_at, channel_message_id text nullable.
- Two new Postgres ENUM types: `template_internal_status` (`draft|in_review|approved|published|archived`), `template_external_status` (`n_a|pending|approved|rejected|paused`). `channel` reuses the existing `conversation_channel` enum.
- RLS `USING (org_id = current_setting('app.org_id')::uuid)` on every new table.
- Hot-path indexes: `(org_id, channel, internal_status)`, `(org_id, external_status) WHERE external_status != 'n_a'`, `(template_id, version)` on versions, `(template_id, created_at DESC)` on reviews.
- SQLAlchemy models — all five — extending `TenantScoped` per `core/campaigns/models.py` pattern.
- Pydantic schemas: `TemplateCreate`, `TemplateUpdate`, `TemplateRead`, `TemplateVersionRead`, `TemplateReviewRead` with field validators (name length 1-120, body_text length 1-65535, subject length 1-998 for email).

Out of scope:
- Service layer (Step 2).
- Router (Step 3).
- Workflow state-transition logic (Step 4).
- Test-send audit-row writes (Step 5 — table exists here, writes wired there).
- WhatsApp + Email backfill (Steps 9 + 10).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_templates_schema.py` | **NEW** — migration |
| `API/src/app/core/templates/__init__.py` | **NEW** — package docstring |
| `API/src/app/core/templates/models.py` | **NEW** — five SQLAlchemy classes |
| `API/src/app/core/templates/schemas.py` | **NEW** — Pydantic shapes |
| `API/tests/templates/__init__.py` | **NEW** — empty |
| `API/tests/templates/test_models_import.py` | **NEW** — import + instantiation smoke |

**~6 files. ~380 lines.**

## Plan

1. Author the Alembic migration. Use `op.execute("CREATE TYPE ...")` for the two new enums; reuse the existing `conversation_channel` enum for `channel`. Create all five tables in topological order (templates → versions/reviews/assets/test_sends). Attach RLS policies. Create indexes.
2. SQLAlchemy models matching the migration verbatim. Each extends `TenantScoped`. Use `mapped_column` (SA 2.x). `Index(...)` declarations in `__table_args__`.
3. Pydantic schemas with `model_config = ConfigDict(from_attributes=True)`. Field validators for length + format.
4. Run migration up and down on the test DB to verify reversibility.
5. Add `test_models_import.py` smoke — imports + minimal instantiation catches typos before Step 2.

## DB changes / migrations

Five new tables + two new enums. Migration reversible (downgrade drops everything in reverse order). Existing pin-test `API/tests/test_table_name_convention.py` covers the `tbl_` prefix — new tables satisfy it without change.

## Tests

- 1 pytest smoke (`test_models_import.py`) — imports + minimal instantiation.
- Migration up-down verified manually via `docker-helper.cmd upgrade head` + `downgrade -1`.

## Smoke

```
1. API/docker-helper.cmd upgrade head — migration applies cleanly.
2. \dt tbl_message_template* — five tables visible.
3. \dT template_*_status — two new enums visible.
4. INSERT row with explicit org_id (after SET app.org_id) — SELECT confirms it back.
5. SELECT without app.org_id set — RLS blocks the row.
6. API/docker-helper.cmd downgrade -1 — clean drop, no orphan enums.
7. uv run pytest API/tests/templates/test_models_import.py — passes.
```

## Risks

- ENUM creation in Alembic must guard against re-creation on partial downgrade. Use `if_not_exists` pattern or wrap in try/except in downgrade.
- Unique `(org_id, lower(name), channel)` requires `CREATE UNIQUE INDEX` with `lower()` expression, not a table-level UniqueConstraint. Document in migration.

## Self-check (10 rules)

`core/templates/` pure core. ✓ org_id + RLS on every table. ✓ No custom-field changes. ✓ N/A dynamic forms. N/A sidebar (Step 5). N/A permissions (Step 3). pack.yaml untouched. ✓ 6 files / ~380 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 1 — Templates schema and models
Files: 6
Verify: five tables created with RLS + indexes; two new enums; models + schemas importable; migration reversible.
Tests: 1 pytest smoke + manual up/down verified.
Awaiting "proceed".
```
