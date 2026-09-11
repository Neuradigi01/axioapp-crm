# Step 1 — Promote `core/templates/variables.py` → `core/variables/`

**Goal:** move the existing 413-line shared registry (parser + renderer + `_CONTACT_VARS`/etc.) out of `core/templates/` into its own `core/variables/` module without behavior change; re-point every import site.
**Phase:** Variables Unification track — step 1/13
**Depends on:** —
**Status:** Pending

## Scope

**In-scope:**
- Create `core/variables/{__init__.py, router.py (empty stub), service.py, data_access.py (empty stub), schemas.py, utils.py, constants.py, models.py (empty stub)}`.
- Move contents of `core/templates/variables.py` into `core/variables/`:
  - `extract_variable_paths`, `reject_jinja_statements`, `render`, `resolve` → `core/variables/utils.py`.
  - `ALLOWED_VARIABLES_BY_CHANNEL`, `_CONTACT_VARS`/`_ORG_VARS`/`_SENDER_VARS`/`_LEAD_VARS`/`_USER_VARS`/`_APPOINTMENT_VARS`/`_QUOTE_VARS`/`_INVOICE_VARS`/`_TASK_VARS`/`_ASSIGNEE_VARS` → `core/variables/constants.py`.
  - `VariableDef` dataclass → `core/variables/schemas.py` (Pydantic v2 model; keep dataclass export as adapter for one release).
- Replace `core/templates/variables.py` with a re-export shim (deleted in Step 11 per deprecation calendar).
- Delete `core/email/variables.py` shim (it currently re-exports; direct callers now import `core.variables.utils`).
- Re-point every import site:
  - `core/templates/service.py`
  - `core/workflows/actions/send.py`, `flow_control.py`, `tagging.py`, `records.py`
  - `core/chatbots/channel_bridge.py` (uses `render_variables` — kept as chatbot-specific wrapper, but the low-level `resolve` import switches to `core.variables.utils`)
  - `core/automation/render.py` (if exists), `core/campaigns/*` renderers
  - `core/email_sequences/` (any residual — track absorbed but files may still reference)
  - Test files.

**Out of scope:**
- Any behavior change (adding fields, changing render semantics).
- Endpoint changes — `/templates/variables/{channel}` continues to work via the shim.
- Frontend changes.

## Files to touch
- `api/src/app/core/variables/__init__.py` (new — re-exports for `from core.variables import ...`)
- `api/src/app/core/variables/utils.py` (new)
- `api/src/app/core/variables/constants.py` (new)
- `api/src/app/core/variables/schemas.py` (new)
- `api/src/app/core/variables/service.py` (new — empty stubs)
- `api/src/app/core/variables/data_access.py` (new — empty stub, only DAL helpers we add in Step 3)
- `api/src/app/core/variables/router.py` (new — empty; wired in Step 4)
- `api/src/app/core/variables/models.py` (new — empty stub; `tbl_variable_stale_refs` added in Step 6)
- `api/src/app/core/templates/variables.py` (modified → shim `from src.app.core.variables.utils import *; from src.app.core.variables.constants import *`)
- `api/src/app/core/email/variables.py` (deleted; callers updated below)
- `api/src/app/core/templates/service.py` (modified — import from `core.variables.utils`)
- `api/src/app/core/workflows/actions/send.py` (modified)
- `api/src/app/core/workflows/actions/flow_control.py` (modified)
- `api/src/app/core/workflows/actions/tagging.py` (modified)
- `api/src/app/core/workflows/actions/records.py` (modified)
- `api/src/app/core/chatbots/channel_bridge.py` (modified — `resolve` import)
- Every other grep hit for `from src.app.core.templates.variables` or `from src.app.core.email.variables`.
- `api/src/app/main.py` — register `core.variables.router` (empty prefix; wired in Step 4).

## Plan
1. Create `core/variables/` folder + all files listed above; utils/constants/schemas populated by moving code verbatim.
2. Replace `core/templates/variables.py` with a shim (`from src.app.core.variables.utils import *; from src.app.core.variables.constants import *; from src.app.core.variables.schemas import VariableDef`).
3. Grep `from src.app.core.templates.variables` + `from src.app.core.email.variables` across `api/` — update every import site. Test files included.
4. Delete `core/email/variables.py` (its callers now import `core.variables.*` directly).
5. Run pytest to confirm zero regressions on templates + workflows + chatbots + automation.
6. Verify `is_visible_to` and event-catalog reads still work (they only use `event_catalog`, not `variables.py` — should be untouched but grep to be sure).

## DB changes / migrations
None.

## Tests to add
- `test_variables_module_reexports_all_public_symbols` — assert `core.variables.utils.render`, `.resolve`, `.extract_variable_paths`, `.reject_jinja_statements` exist.
- `test_variables_module_constants_match_template_registry_snapshot` — assert `ALLOWED_VARIABLES_BY_CHANNEL` byte-equal to pre-move snapshot.
- `test_templates_variables_shim_still_works` — `from src.app.core.templates.variables import render` still returns the moved function (backward-compat for one release).
- Pin-test: `test_no_import_of_core_templates_variables_outside_shim` — walks `api/src` and asserts no non-shim file imports `core.templates.variables.<anything>` (allow-list: the shim itself).
- Existing template render tests, workflow action tests, chatbot tests all still pass.

## Verification checklist

**Backend:**
- `uv run pytest api/tests/test_templates_render.py -x` — passes.
- `uv run pytest api/tests/test_workflows_actions.py -x` — passes.
- `uv run pytest api/tests/test_chatbots_channel_bridge.py -x` — passes.
- `uv run pytest api/tests/test_automation_render.py -x` — passes.
- `uv run pytest api/tests/test_variables_module_reexports.py -x` — passes (new).
- `grep -r "from src.app.core.templates.variables" api/src` — returns 0 (except the shim file itself).
- `grep -r "from src.app.core.email.variables" api/src` — returns 0.

**Frontend:**
- No changes; existing endpoints (`/templates/variables/{channel}`, `/chatbots/variables`) still respond.
- Templates editor + Chatbots editor smoke-test open and render.

**Code review:**
- `core/variables/utils.py` is pure Python — no DB imports.
- `core/variables/constants.py` is pure data — no runtime side-effects.
- `core/variables/schemas.py` uses Pydantic v2.
- `core/templates/variables.py` shim < 10 lines.

## Self-check (10 rules)
- [ ] Rule 1: `core/` doesn't import `packs/`. Move preserves this.
- [ ] Rule 2: No new DB tables.
- [ ] Rule 3: Custom-fields model untouched.
- [ ] Rule 4: N/A (no forms).
- [ ] Rule 5: N/A (no sidebar).
- [ ] Rule 6: No new perm keys.
- [ ] Rule 7: N/A (no pack).
- [ ] Rule 8: ~15 files touched (mostly moves + import repointing) — under limit.
- [ ] Rule 9: Stop and report after this step.
- [ ] Rule 10: No TODOs; shim deletion tracked in `deprecations.md` (Step 11).

## Stop & report
Use the master-prompt stop template; await "proceed".
