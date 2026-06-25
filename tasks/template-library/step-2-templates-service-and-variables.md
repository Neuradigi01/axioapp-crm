# Step 2 — Templates service and variable engine

**Goal:** Service-layer CRUD + version creation; promote the existing variable engine into `core/templates/variables.py` as a channel-aware shared registry. No HTTP routes, no workflow state transitions yet.
**Status:** COMPLETED — `core/templates/exceptions.py` (TemplateNotFound / DuplicateTemplateName / TemplateLocked), `core/templates/variables.py` (promoted from `core/email/variables.py` + added `VariableDef`, `ALLOWED_VARIABLES_BY_CHANNEL`, `variables_for_channel`, lenient `resolve()` alongside strict `render()`, and `extract_variables` alias), `core/email/variables.py` slimmed to a 6-line re-export shim (existing `core/email_templates/service.py` consumer keeps working), `core/templates/service.py` (`create_template` / `get_template` / `list_templates` / `update_template` / `archive_template` / `list_versions` / `get_version` — all RLS-scoped, version-row written atomically with the parent, edit-lock on non-draft, idempotent archive, channel-coherence check on PATCH). Imports confirmed resolving in the api container. 6 + 11 = 17 pytest cases ready in `test_service.py` + `test_variables.py`; pytest run deferred per `feedback_pause_before_pytest.md` memory. **Post-Step-7 DAL refactor (2026-06-25):** queries extracted into `core/templates/data_access/templates.py` (`get_template`, `list_templates`) + `core/templates/data_access/versions.py` (`get_version`, `list_versions`); `__init__.py` re-exports the 4 functions. `service.py` reads now delegate to `data_access`; writes (create / update / archive — commits + version-row inserts) stay in `service.py`. Matches the project's per-module `core/<module>/data_access/` convention.
**Depends on:** Step 1 (schema + models). Re-houses `core/email/variables.py`.

---

## Scope

In-scope:
- `core/templates/service.py`:
  - `create_template(org_id, payload, user_id) → MessageTemplate` — inserts template row + initial version row (version=1) inside a single transaction. Rejects duplicate `(org_id, lower(name), channel)`.
  - `get_template(org_id, template_id) → MessageTemplate` — RLS-scoped read with current version eager-loaded.
  - `list_templates(org_id, *, channel?, internal_status?, external_status?, q?, limit, offset) → list[MessageTemplate]` — filterable list; `q` searches `name + body_text`.
  - `update_template(org_id, template_id, payload, user_id) → MessageTemplate` — bumps `current_version`, writes a new `tbl_message_template_versions` row, updates mutable columns on the parent. Rejects edits when `internal_status in (in_review, approved, published)` — caller must move it back to draft first (workflow lives in Step 4; service just enforces the lock).
  - `archive_template(org_id, template_id, user_id) → MessageTemplate` — sets `internal_status='archived'`, does NOT touch external_status. Used by Step 4's archive endpoint.
  - `list_versions(org_id, template_id, limit, offset)` and `get_version(org_id, template_id, version)`.
- `core/templates/variables.py`:
  - Re-housing of `core/email/variables.py` as `core/templates/variables.py`. The original keeps a thin re-export shim during this step (deleted in Step 10).
  - Per-channel allowed-variable registry: `dict[ConversationChannel, list[VariableDef]]` so the future editor (Step 7) knows which `{{tags}}` make sense per channel.
  - `VariableDef`: key (`contact.first_name`), label (`Contact first name`), type (`string|int|date|currency|url`), required (bool), default (str|None).
  - `resolve(template_body, context) → str` — Jinja-safe; missing-variable behavior = empty string (not `{{undefined}}`) to avoid leaking template syntax to customers.
  - `extract_variables(template_body) → list[str]` — parses the body, returns the set of `{{...}}` references; service uses this to populate `tbl_message_templates.variables`.
- `core/templates/exceptions.py`:
  - `TemplateNotFound`, `DuplicateTemplateName`, `TemplateLocked` (raised when caller tries to edit a non-draft template).
- Unit tests for service + variables + extract/resolve.

Out of scope:
- HTTP routes (Step 3).
- Workflow state transitions (Step 4) — service has the locked-template check but the transitions themselves are in Step 4.
- Migrating callers of `core/email/variables.py` (deferred to Step 10).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/templates/service.py` | **NEW** |
| `API/src/app/core/templates/variables.py` | **NEW** |
| `API/src/app/core/email/variables.py` | edit — slim down to `from src.app.core.templates.variables import *` shim |
| `API/src/app/core/templates/exceptions.py` | **NEW** |
| `API/tests/templates/test_service.py` | **NEW** |
| `API/tests/templates/test_variables.py` | **NEW** |

**~6 files. ~520 lines.**

## Plan

1. Create `variables.py` by copying `core/email/variables.py` contents and expanding the registry per channel: email (existing set), WhatsApp (subset that makes sense for WA), SMS (very small set — no HTML), FB/IG/push (small set).
2. Reduce `core/email/variables.py` to a re-export shim — Step 10 deletes it.
3. Author `exceptions.py` + `service.py`. Use existing `db.async_session` pattern (see `core/campaigns/service.py`).
4. Wire `extract_variables` into `create_template` and `update_template` — the stored `variables` column is the parsed set, not whatever the caller supplied.
5. Tests: CRUD happy path, RLS isolation, duplicate-name rejection, edit-lock on non-draft, variable parser correctness (nested braces, unclosed tags, escaping).

## DB changes / migrations

None — Step 1 migration already supplied everything.

## Tests

10 pytest cases:
- `test_create_template_writes_version_1`
- `test_create_template_rejects_duplicate_name_same_channel`
- `test_create_template_allows_same_name_different_channel`
- `test_update_template_bumps_version_and_writes_history`
- `test_update_template_locked_when_in_review`
- `test_archive_template_idempotent`
- `test_list_templates_filters_by_channel_and_status`
- `test_variables_extract_finds_all_braces`
- `test_variables_resolve_missing_yields_empty`
- `test_variables_resolve_xss_safe`

## Smoke

```
1. uv run pytest API/tests/templates/ — all green.
2. Python shell via docker-helper.cmd: instantiate service, create template, update it, confirm version=2 row exists.
```

## Risks

- Re-export shim in `core/email/variables.py` may cause import cycle if `templates.variables` ever imports from `core.email`. Avoid by keeping `templates.variables` self-contained.
- File-line count creeping past 400. Tests carry half the count — body of service.py + variables.py + exceptions.py stays under 300.

## Self-check (10 rules)

`core/templates/`. ✓ RLS-scoped queries. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. N/A permissions (Step 3). pack.yaml untouched. ✓ 6 files / ~520 lines (tests-heavy). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 2 — Templates service and variable engine
Files: 6
Verify: service CRUD + version history + variable extract/resolve working under RLS.
Tests: 10 pytest cases.
Awaiting "proceed".
```
