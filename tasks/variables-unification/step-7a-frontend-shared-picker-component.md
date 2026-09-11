# Step 7a — Generalise `shared/variable-picker/` component

**Goal:** extend the existing chatbots-only picker at `APP/src/app/features/user/core/shared/variable-picker/variable-picker.component.ts` to handle any surface (Templates, Workflows, Chatbots, Automation conditions, Campaigns). Adds `entity` / `channel` / `event` inputs; type-ahead search; recently-used pinning; fallback-value input at insertion; input / textarea / contenteditable cursor support.
**Phase:** Variables Unification track — step 7a/13
**Depends on:** Step 4
**Status:** Pending

## Scope

**In-scope:**
- Extend `variable-picker.component.ts` inputs:
  - `entity: string` (was: implied chatbot).
  - `channel: string` (new).
  - `event: string | null` (new — for `{{event.*}}` group).
  - `target: 'input' | 'textarea' | 'contenteditable'` (new — cursor-insertion strategy).
  - `surface: string` (new — for localStorage-keyed recently-used, e.g. `"templates.body"`, `"workflow.action.send.recipient"`).
  - `(insert): EventEmitter<{ path: string, default_value?: string }>`.
- Type-ahead search input at top of dropdown (`<input>`, fuzzy match on `path` + `label`).
- Recently-used group pinned to top (localStorage keyed by `${user_id}:${surface}`; max 5 entries; last-N behavior).
- Fallback-value input prompt appears inline at insertion time — user can leave blank (emits `path` only) or fill (emits `{{path | default:"..."}}` composed token).
- "Not resolvable here" badge on paths where `is_resolvable_here=false` (styled amber-warning banner pattern per project standard).
- Cursor-insertion helper module: `cursor-insert.util.ts` — one function per target type (`insertAtCaret_Input`, `insertAtCaret_Textarea`, `insertAtCaret_ContentEditable`), preserves undo stack where possible.
- Keyboard nav (↑↓ Enter Esc), click-outside close.

**Out of scope:**
- Data-fetching service (Step 7b).
- Surface migrations (Steps 8-10).

## Files to touch
- `APP/src/app/features/user/core/shared/variable-picker/variable-picker.component.ts` (modified).
- `APP/src/app/features/user/core/shared/variable-picker/variable-picker.component.html` (modified — search input, recently-used, badge, fallback prompt).
- `APP/src/app/features/user/core/shared/variable-picker/cursor-insert.util.ts` (new).
- `APP/src/app/features/user/core/shared/variable-picker/recently-used.service.ts` (new — localStorage helper).
- `APP/src/app/features/user/core/shared/variable-picker/variable-picker.component.spec.ts` (extended).
- `APP/src/app/features/user/core/shared/variable-picker/*.md` (README if exists — update).

## Plan
1. Extend component API (inputs, output).
2. Build cursor-insert helpers + unit tests for each target type.
3. Recently-used service (localStorage read/write, cap 5).
4. Type-ahead search — filters visible variables client-side.
5. Fallback-value input — inline field appearing on hover/click of a variable row.
6. Amber "not resolvable" badge — matches standard project pattern.
7. Playwright tests.

## DB changes / migrations
None.

## Tests to add
- Component spec: renders search input, filters on typing.
- Component spec: recently-used group appears at top after insertion; capped at 5.
- Component spec: fallback-value emits composed `{{path | default:"..."}}` when filled.
- Component spec: `is_resolvable_here=false` renders badge.
- Playwright: insertion into `<input>` places token at cursor, cursor advances.
- Playwright: insertion into `<textarea>` same.
- Playwright: insertion into `contenteditable` (Templates body) same.
- Playwright: keyboard nav ↑↓ Enter Esc.

## Verification checklist
- Frontend: `npm run test -- variable-picker` passes.
- Frontend: `npx playwright test variable-picker.spec.ts` passes.
- Frontend: manual open Templates editor + existing surfaces — no visual regression.
- Frontend: prettier + eslint clean per project memory (`npx --no-install prettier --write` on modified files).

## Self-check
- [ ] Rule 1: N/A (frontend).
- [ ] Rules 2-7: N/A.
- [ ] Rule 8: ~6 files.
- [ ] Rule 9: stop and report.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
