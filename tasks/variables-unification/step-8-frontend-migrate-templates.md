# Step 8 — Migrate Templates editor to shared picker

**Goal:** replace `APP/.../templates/editor/variable-picker.component.ts` (renegade #1) with the shared `<crm-variable-picker>`. Wire on: subject `<input>`, preview-text `<input>`, body `contenteditable`.
**Phase:** Variables Unification track — step 8/13
**Depends on:** Steps 7a, 7b
**Status:** Pending

## Scope

**In-scope:**
- Replace the renegade component with the shared one. Delete `variable-picker.component.ts/.html` in templates/editor.
- Wire pickers on 3 template fields: subject (input), preview-text (input), body (contenteditable).
- `TemplatesApiService.variables(channel)` continues to proxy through — new endpoint feeds it. Scheduled for retirement in Step 11.
- Sample-preview pane on the right uses `VariableDef.sample` — no code change if already reading `sample`.

**Out of scope:**
- Retiring old `/templates/variables/{channel}` endpoint (Step 11).

## Files to touch
- `APP/src/app/features/user/core/templates/editor/variable-picker.component.ts` (deleted).
- `APP/src/app/features/user/core/templates/editor/variable-picker.component.html` (deleted).
- `APP/src/app/features/user/core/templates/editor/template-editor.page.ts` (modified — swap in `<crm-variable-picker>` on 3 fields).
- `APP/src/app/features/user/core/templates/editor/template-editor.page.html` (modified — 3 wire-ups).

## Plan
1. Delete renegade files.
2. Import shared component + registry service in `template-editor.page.ts`.
3. Wire `<crm-variable-picker [entity]="'contact'" [channel]="template.channel" [event]="template.linked_event ?? null" [target]="'input'" [surface]="'templates.subject'" (insert)="onInsertSubject($event)"/>` etc.
4. Playwright smoke on all 3 surfaces.

## Tests to add
- Playwright: templates editor — insert variable into subject, preview-text, body — token appears at cursor, form-dirty flag flips.

## Verification checklist
- Frontend: prettier + eslint clean.
- Frontend: manual open templates editor, insert variables in each field.

## Self-check
- [ ] Rules N/A / clean.
- [ ] Rule 8: 4 files.

## Stop & report
Await "proceed".
