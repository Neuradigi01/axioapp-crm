# Step 10 — Frontend: Template editor (Settings) + compose-from-template in contacts/leads

**Goal:** Org-scoped library of email templates. Editor with subject + body + variable picker + live preview against a real contact. Template picker appears in the existing compose-bar inside contacts/leads/conversations so a rep can select a template and have it rendered into the compose field.
**Track:** App Updates → Email
**Status:** Pending
**Depends on:** Step 6 (templates backend), Step 9 (settings-tab plumbing established).

---

## Scope

In-scope:

- New page `/user/settings/email-templates` (Owner + reps with `email.templates.manage` can create/edit; everyone with `email.read` can list + use).
- Components:
  - `template-list.component.ts/.html` — table with name, subject preview, last-used, created-by, actions (edit, duplicate, delete).
  - `template-editor.component.ts/.html` — form: name, subject, body (textarea-based HTML editor for v1 — no WYSIWYG dependency), variables sidebar (categorised: Contact, Lead, User, Org) where clicking a variable inserts it at the caret. "Preview" tab renders against a selectable contact.
  - `template-picker.component.ts/.html` — reusable inline picker that appears as a "Use template" button next to the compose-bar's Send button. Shows a popover list filtered by name. On select, calls `/email/templates/{id}/render?contact_id=&lead_id=` and fills the compose body.
- `email-templates-api.service.ts` — list/create/update/delete/render.
- Wire `template-picker` into:
  - Contacts detail page compose bar.
  - Leads detail page compose bar.
  - Conversations page compose bar (when `channel='email'`).
- Tailwind only. No external editor library — plain `<textarea>` with monospace, plus a "preview" tab. (WYSIWYG is v2.)

Out of scope:

- WYSIWYG editor (Trix, TipTap, etc.) — v2.
- Inline image attachments — v2.
- Template categories / folders — v2; filter by name is enough for v1.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/email-templates/template-list.component.ts` | created |
| `app/src/app/features/user/core/settings/email-templates/template-list.component.html` | created |
| `app/src/app/features/user/core/settings/email-templates/template-editor.component.ts` | created |
| `app/src/app/features/user/core/settings/email-templates/template-editor.component.html` | created |
| `app/src/app/features/user/core/settings/email-templates/template-editor.page.ts` | created — route shell for create + edit |
| `app/src/app/features/user/core/shared/email/template-picker.component.ts` | created |
| `app/src/app/features/user/core/shared/email/template-picker.component.html` | created |
| `app/src/app/features/user/core/services/email-templates-api.service.ts` | created |
| `app/src/app/features/user/user.routes.ts` | modified — add `/user/settings/email-templates` + `/new` + `/:id/edit` routes |
| `app/src/app/features/user/core/settings/settings-page.component.ts` | modified — add "Email Templates" tab link |
| `app/src/app/features/user/core/contacts/contact-detail.page.html` | modified — inline template-picker into compose bar |
| `app/src/app/features/user/core/leads/lead-detail.page.html` | modified — inline template-picker into compose bar |
| `app/src/app/features/user/core/conversations/compose-bar.component.html` | modified — inline template-picker when channel='email' |
| `app/src/app/app.config.ts` | modified — register lucide icons (`type`, `eye`, `copy`) |

**14 files.** Largest step in the track for frontend; splits cleanly between editor surface (8 files) and picker integration (6 files). Could be split into 10a (editor) + 10b (picker integration) if reviewer load is an issue.

## Plan

1. Service: typed client. `list()`, `get(id)`, `create(payload)`, `update(id, payload)`, `delete(id)`, `render(id, {contactId, leadId})`.
2. Editor: reactive form with `name`, `subject`, `body_html` controls. Variables sidebar fetched from `/email/variables/registry` (a static endpoint added in Step 6's router that returns the allowed variable paths grouped by category). Inserting a variable just splices `{{ <path> }}` at the textarea selectionStart.
3. Preview tab: select a real contact (typeahead via existing contacts API); POST to `/render?contact_id=…`; show subject + body_html in an iframe with `sandbox` for safety.
4. List: table with debounced name filter. Soft-delete via DELETE.
5. Picker: signal-based, popover positioned via existing portal pattern. List filtered by name. On select, POST to `/render?contact_id=…&lead_id=…` and emit an event with `{subject, body_html, body_text}` that the parent compose bar consumes.
6. Routes: `/user/settings/email-templates` (list), `/new` (editor), `/:id/edit` (editor).
7. Settings tab registration + lucide icons.

## Tests

- `email-templates-api.service.spec.ts` — HTTP wiring.
- `template-picker.component.spec.ts` — picker emits selection with rendered body.

## Smoke

```powershell
cd app
npm run start

# As Owner:
# /user/settings/email-templates → empty list, "Create template" CTA
# Click → editor opens
# Type "Hi {{contact.first_name}}, here is a quote for your project..." in body
# Click Preview tab → pick a contact → variables resolve
# Save → back to list, row visible

# On contact detail page:
# Compose bar shows "Use template" button → popover lists the saved template
# Pick it → compose body fills with the rendered substitution
# Send → email goes out via the connected Gmail (verified end-to-end)
```

## Risks

- **Iframe preview XSS.** Render output is autoescaped server-side (Step 6) but the iframe still gets `sandbox` to be safe.
- **Variable picker drift.** If the backend variable registry adds a category and the frontend hardcodes the categories, sidebar misses new ones. Mitigation: registry endpoint returns categories + the sidebar renders them dynamically.
- **Compose-bar regressions.** Adding template-picker to three compose surfaces risks breaking existing channels (WhatsApp, SMS-when-it-lands). Mitigation: picker is only mounted when channel is `email`; covered by `@if (channel() === 'email')`.

## Rollback

Delete files. Revert user.routes.ts + settings-page registry + the three compose-bar templates + app.config.ts. Backend templates remain — Settings just loses the UI to manage them.
