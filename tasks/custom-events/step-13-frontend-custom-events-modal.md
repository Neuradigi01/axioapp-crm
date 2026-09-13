# Step 13 — Frontend create/edit modal + payload schema builder + sample preview + reserved-name validation

**Goal:** create/edit modal for custom events. Reuses the shared schema-builder widget from Track A. Inline reserved-name validation. Live sample-payload preview. Allow test-fire from dirty form (with "unsaved" banner).
**Phase:** Custom Events track — step 13/17
**Depends on:** Steps 6, 12, Track A Step 7a (shared component)
**Status:** Pending

## Scope

**In-scope:**
- Create/Edit modal component:
  - Name (unprefixed) — inline validation via debounced backend check (`/custom-events/validate-name?name=<x>` — new lightweight endpoint returning `{available: bool, reason?: "reserved"|"conflict"|"invalid_format"}`).
  - Display label.
  - Category.
  - Payload schema builder: reuses shared component from Track A (`<crm-schema-builder>`) — declares properties (name, type, required, enum, max_length). If Track A hasn't shipped, this step imports the widget from `APP/.../shared/schema-builder/` (creates it as a smaller sub-component owned by this track and later moves to shared).
  - Live sample-payload JSON preview panel — regenerates on schema change (type-appropriate defaults per property).
  - "Test fire" button — allowed even with dirty form; shows "unsaved schema" banner + fires against the dirty schema in memory (result in Test fires tab).
  - Save (Owner-only): PUT with `If-Match` header from `updated_at`.

**Out of scope:**
- Detail page (Step 14).

## Files to touch
- `APP/src/app/features/user/core/settings/custom-events/create-edit-modal.component.ts/.html` (new).
- `APP/src/app/features/user/core/settings/custom-events/schema-builder-widget.component.ts/.html` (new — will be moved to shared if Track A hasn't shipped).
- `APP/src/app/features/user/core/settings/custom-events/sample-preview.component.ts/.html` (new).
- `APP/src/app/features/user/core/settings/custom-events/name-validator.directive.ts` (new — inline validation).
- `core/public_ingest/custom_events/router.py` (modified — add `GET /validate-name` endpoint).
- Tests.

## Plan
1. Modal shell.
2. Name validator directive + backend endpoint.
3. Schema builder widget (reuse or new).
4. Sample preview.
5. Test-fire button with unsaved banner.
6. Playwright.

## Tests to add
- Playwright: type reserved name → red inline warning "This name conflicts with a system event."
- Playwright: type valid name → green check.
- Playwright: add property in builder → sample preview updates live.
- Playwright: dirty form + test-fire → banner "unsaved schema"; fires successfully.
- Playwright: Owner can save (edit); Admin sees create-only.

## Verification checklist
- Frontend: prettier + eslint clean.
- Frontend: manual create + edit flows.

## Self-check
- [ ] Rule N/A / clean.
- [ ] Rule 8: ~8 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
