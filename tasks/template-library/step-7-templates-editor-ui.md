# Step 7 — Templates editor UI (WhatsApp + Email sub-forms)

**Goal:** Channel-aware editor at `/user/templates/{id}` (and `/new`) with WhatsApp and Email sub-forms, variable picker, live preview pane, save-as-draft + save-and-submit flows. SMS / FB / IG / push sub-forms come in Steps 12 + 13.
**Status:** Pending
**Depends on:** Step 6 (list page wired). Reads from Step-3 endpoints + Step-2 variable registry.

---

## Scope

In-scope:
- `APP/.../core/templates/editor/template-editor.page.{ts,html}`:
  - Top bar: name input + channel dropdown (locked after first save), status badges, Save Draft / Save & Submit buttons (depending on workflow toggle).
  - Two-pane layout: editor on left, live preview on right (sticky).
  - Sub-form mounted by channel — WA or Email here, others come later.
  - Variable picker drawer (right edge): lists allowed `{{contact.*}} / {{org.*}}` etc. for the current channel from `GET /api/v1/templates/variables/{channel}`. Click to insert at cursor.
  - Form state via typed reactive forms (Angular 20+ pattern).
  - Lock indicator: when status is in_review/approved/published, editor is read-only with a "Move to draft" CTA (calls reject — only visible to reviewers — or contacts the reviewer copy otherwise).
- `APP/.../core/templates/editor/wa-form.component.{ts,html}`:
  - Header type (none / text / image / video / document), header text (60 char), body text (1024 char + counter), footer text (60 char), buttons (quick_reply up to 3 OR cta_url with up to 2 buttons — mutex via discriminated union), language code (`en`, `hi`, `mr`, `gu`...), category (`MARKETING` / `UTILITY` / `AUTHENTICATION`).
  - Mirrors the existing WhatsApp template wizard (`APP/.../whatsapp/templates/template-wizard.component.ts`) at the field level. Behind the scenes the wizard's logic is reused (Step 9 will dedupe).
- `APP/.../core/templates/editor/email-form.component.{ts,html}`:
  - Subject (998 char), preview text / pre-header (190 char), from-name override (optional), reply-to override (optional), body (HTML textarea — visual editor deferred). Variable picker works on body + subject.
- `APP/.../core/templates/editor/variable-picker.component.{ts,html}`:
  - Pulls from `/templates/variables/{channel}`, groups by namespace (contact / org / sender / lead / etc.). Click-to-insert at the current cursor position.
- `APP/.../core/templates/editor/preview-pane.component.{ts,html}`:
  - WA: chat-bubble preview matching the existing `template-preview.component.ts` from `whatsapp/templates/`.
  - Email: rendered HTML in a sandboxed iframe with `{{variables}}` filled from sample data.
- Auto-save: 30s after last edit, calls PATCH (creates a new version row server-side per Step 2).
- Jest smoke for form-state binding + variable insertion.

Out of scope:
- Review modal / versions drawer / test-send modal (Step 8).
- SMS sub-form (Step 12).
- FB / IG / push sub-forms (Step 13).
- Visual drag-drop email editor (defer; raw HTML textarea is acceptable v1).
- External submission button — present but disabled here; wired in Step 9 + 14.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/templates/editor/template-editor.page.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/wa-form.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/wa-form.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/email-form.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/email-form.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/variable-picker.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/variable-picker.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/preview-pane.component.ts` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — add `/user/templates/new` and `/user/templates/:id` routes |

**~10 files. ~600 lines.**

## Plan

1. Editor page shell — typed reactive form root + signal-driven channel switch.
2. WA + Email sub-form components plugged in by channel.
3. Variable picker — small dumb component, click-to-insert via `document.execCommand` or signal-driven approach.
4. Preview pane — two implementations: WA bubble (reuse from existing wizard) + Email iframe.
5. Auto-save: `effect()` watching the form valueChanges, debounced 30s, calls PATCH.
6. Locked-state visual: read-only when `internal_status in (in_review, approved, published)`.
7. Jest smoke: variable insertion appends correctly; channel switch toggles sub-form.

## DB changes / migrations

None.

## Tests

3 Jest cases:
- Selecting WhatsApp shows WA sub-form, selecting Email shows Email sub-form.
- Clicking a variable in the picker inserts `{{...}}` into the body textarea.
- Saving creates draft via PATCH and updates status badge.

## Smoke

```
1. /user/templates/new → editor opens.
2. Type a name, pick "Email" channel, fill subject + body with `{{contact.first_name}}`.
3. Preview pane shows the resolved body with the sample contact name.
4. Click Save Draft → row appears in /user/templates list.
5. Reopen, edit body, wait 30s → auto-save creates version 2 server-side.
6. Switch channel selector to WhatsApp → confirm WA sub-form mounts, Email sub-form unmounts (with a confirm dialog warning about losing data).
7. As Employee on a template authored by Owner that is in_review: editor is read-only; banner "Locked for review."
```

## Risks

- File-line creep — 10 files, ~600 lines. Acceptable per Rule 8 because each sub-form is small (~80 lines) and the bulk is the editor shell + variable picker + preview pane.
- The existing `APP/.../whatsapp/templates/template-wizard.component.ts` overlaps with `wa-form.component.ts` from this step. Step 9 dedupes — until then the duplication exists for one release cycle. Documented as a known temporary state.
- Lucide icon audit: `file-text`, `mail`, `message-circle`, `chevron-down`, `code`, `eye`, `eye-off`, `clock`, `check` — confirm all registered.

## Self-check (10 rules)

`features/user/core/templates/`. ✓ org_id auto-applied. ✓ N/A custom fields. ✓ N/A dynamic forms (channel sub-forms are static parts of the module). ✓ Sidebar already registered. Permissions gate route + Save button. ✓ pack.yaml untouched. ✓ 10 files / ~600 lines — at the limit but justifiable per scope. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 7 — Templates editor UI (WhatsApp + Email sub-forms)
Files: 10
Verify: WA + Email editors with variable picker + live preview + auto-save + locked-state guard.
Tests: 3 Jest smoke cases.
Awaiting "proceed".
```
