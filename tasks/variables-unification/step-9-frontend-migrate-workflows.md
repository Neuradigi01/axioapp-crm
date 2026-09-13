# Step 9 — Migrate Workflows editor to shared picker + delete hardcoded map

**Goal:** replace `APP/.../workflows/canvas/variable-picker.component.ts` (renegade #2) with the shared one. Delete `VARIABLE_GROUPS_BY_EVENT_PREFIX` in `editor-contract.ts`. Wire pickers on every workflow action-config input (recipient email, subject, body, tag name, task title, wait duration text, HTTP URL, HTTP body).
**Phase:** Variables Unification track — step 9/13
**Depends on:** Steps 7a, 7b
**Status:** Pending

## Scope

**In-scope:**
- Replace `workflows/canvas/variable-picker.component.ts` with a shared-component wire-up.
- Delete `VARIABLE_GROUPS_BY_EVENT_PREFIX` from `editor-contract.ts`. Keep the event → entity map (`event_prefix → in_scope_entities`) if it exists — that's still needed to pass the right `entity` prop to the picker.
- Wire pickers in every action editor:
  - Send Email → recipient, subject, body, cc/bcc.
  - Send WhatsApp → recipient, body params.
  - Send SMS → recipient, body.
  - Update Field → value.
  - Add Tag / Remove Tag → tag name.
  - Create Task → title, description.
  - Wait → duration (if text field with variable support).
  - HTTP Request → URL, headers, body.
  - Assign Owner → user reference (variable-based selectors).
  - Condition builder → left-side path + right-side value both use picker.

**Out of scope:**
- Automation conditions builder (Step 10b — separate module).

## Files to touch
- `APP/src/app/features/user/core/workflows/canvas/variable-picker.component.ts` (deleted).
- `APP/src/app/features/user/core/workflows/canvas/variable-picker.component.html` (deleted).
- `APP/src/app/features/user/core/workflows/canvas/editors/editor-contract.ts` (modified — delete `VARIABLE_GROUPS_BY_EVENT_PREFIX`; keep event→entity map).
- `APP/src/app/features/user/core/workflows/canvas/editors/action-*.component.ts` (each modified — swap in shared picker).
- Playwright.

## Plan
1. Delete renegade + hardcoded map.
2. Wire shared picker in each action editor.
3. Confirm event context correctly threaded (trigger's event → entity → picker's `[event]` prop).
4. Playwright smoke covering the top-5 action types.

## Tests to add
- Playwright: workflow editor with `lead.status_changed` trigger — picker in Send Email action shows `event.from_stage_id` / `event.to_stage_id` under Event group.
- Playwright: workflow editor with `custom.order.paid` trigger (once Track B ships) — picker shows event payload keys.
- Playwright: condition builder picker inserts on both sides.

## Verification checklist
- Frontend: prettier + eslint clean.
- Frontend: no hardcoded arrays remain (Step 11 pin-test will catch).

## Self-check
- [ ] Rules N/A / clean.
- [ ] Rule 8: ~8 files (action editors) — at limit. Sub-split if larger.

## Stop & report
Await "proceed".
