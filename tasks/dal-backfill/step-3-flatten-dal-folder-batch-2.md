# Step 3 — Flatten `data_access/` folder → `data_access.py` (templates, tenants, users, integrations/whatsapp)

**Goal:** Convert the remaining four `data_access/` folders to single `data_access.py` files. Pure relocation; behaviour preserved.
**Status:** COMPLETED
**Depends on:** Step 2 (same mechanical pattern).

---

## Scope

In-scope:
- `core/templates/data_access/` → `core/templates/data_access.py`
- `core/tenants/data_access/` → `core/tenants/data_access.py`
- `core/users/data_access/` → `core/users/data_access.py`
- `core/integrations/whatsapp/data_access/` → `core/integrations/whatsapp/data_access.py`

Out of scope: same as Step 2.

## Files to touch

Same shape as Step 2 — per-module flatten + caller import sweep.

**~8 files modified, ~9 files deleted, ~400 lines moved.**

Special notes:
- **templates** is the largest DAL folder (entities: templates + versions). Flattening may approach the 400-line line — if so, split this step into two and treat `templates` alone as its own sub-step.
- **users** has cross-entity helpers (memberships → users). After flatten, these become local function calls.
- **integrations/whatsapp** is nested deeper than usual; the data_access folder sits at `core/integrations/whatsapp/data_access/`. The new file lives at `core/integrations/whatsapp/data_access.py`. Callers use `from src.app.core.integrations.whatsapp import data_access`.

## Plan

Identical to Step 2. Per module:
1. Read all sub-files + `__init__.py`.
2. Create flat `data_access.py`.
3. Delete the folder.
4. Sweep imports.
5. Boot + smoke.

## DB changes / migrations

None.

## Tests

- Run existing module pytests.

## Smoke

- **templates:** `/user/templates` list loads; create a draft.
- **tenants:** Settings → General → save → reload → persists.
- **users:** Settings → Users → list loads.
- **integrations/whatsapp:** Settings → Integrations → WhatsApp → list loads.

## Risks

- `templates` may exceed step size. If line count > 400, split out `templates` as its own step.
- `integrations/whatsapp` is referenced as `whatsapp_da` in some callers per the existing aliasing convention. Sweep all alias forms.

## Self-check (10 rules)

Pure relocation. All 10 rules unchanged. ✓ Watch the size on templates. ✓ Stop-and-report. ✓
