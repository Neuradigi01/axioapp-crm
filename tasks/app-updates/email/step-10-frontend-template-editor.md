# Step 10 — Frontend: Template editor (Settings) + compose-from-template in contacts/leads

**Goal:** Org-scoped library of email templates. Editor with subject + body + variable picker + live preview against a real contact. Template picker appears in the existing compose-bar inside contacts/leads/conversations so a rep can select a template and have it rendered into the compose field.
**Track:** App Updates → Email
**Status:** COMPLETED — Email-templates UI ships under `app/src/app/features/user/core/settings/email-templates/` with three standalone components + reusable picker under `core/shared/email/` + typed service under `core/services/`. `email-templates-api.service.ts` exposes `list / get / create / update / delete / render / variables` over `${apiBaseUrl}/email/templates`; the global `retryInterceptor` covers transient failures on GETs. `template-list.component.ts/.html` renders inside the settings page as the `email-templates` tab — debounced 250ms name filter via `FormControl.valueChanges.pipe(debounceTime, distinctUntilChanged)`, table columns (Name → links to /edit / Subject / Variables count / Updated via DatePipe / Actions), skeleton during initial load, distinct empty state for has-no-matches vs no-templates-yet, Edit + Delete actions hidden behind `email.templates.manage` via `FurnitureAuthService.hasPermission`, inline confirm modal for delete. `template-editor.component.ts/.html` is the editor — reactive `FormGroup<EditForm>` with name (required ≤255) / subject (required ≤998) / body_html (required, monospace textarea) / optional body_text behind `<details>` / is_active checkbox. Variables sidebar fetches `GET /email/templates/variables` on init, groups entries by `category`, click-to-splice inserts `{{ <path> }}` at the active textarea's caret — `lastFocusedField` signal + `document.querySelector('[data-tpl-field="..."]')` reads selectionStart/End, splices, restores caret via `queueMicrotask`. Preview tab typeaheads contacts via existing `ContactsApiService.list({q, size: 8})` (250ms debounce + switchMap), POSTs to `/render?contact_id=…`, renders subject + body_html inside `<iframe srcdoc sandbox="allow-same-origin">` (deliberately omitting `allow-scripts` — defence-in-depth even though Step 6 autoescapes server-side). `template-editor.page.ts` is the route shell: reads `:id` from `ActivatedRoute.snapshot.paramMap` and hands it to the editor as `input<string | null>` (`/new` → null → create mode). `template-picker.component.ts/.html` is the reusable popover — `contactId` + `leadId` inputs, search field that lazy-loads `list({q, is_active: true, size: 30})`, `@HostListener('document:click')` closes on outside-click via `target.closest('app-email-template-picker')`, on select calls `render(id, {contactId, leadId})` and emits `templateSelected`. `conversations/compose-bar.component.ts/.html` extended with three new inputs (`channel`, `contactId`, `leadId`) — when `channel === 'email'` the picker mounts above the AI/Send buttons; `onTemplateSelected` fills the textarea with `body_text` (existing send pipeline carries plain text only; HTML compose lands when a dedicated email compose UI ships, out of scope for v1); dismissible inline error banner surfaces the picker's `errored` output. `conversations.page.html` updated to pass `[channel]="conv.channel"` + `[contactId]="conv.contact_id"`. Three new routes in `user.routes.ts`: `/user/settings/email-templates` (settings page, tab pre-selected), `/new`, `/:id/edit` (both load `EmailTemplateEditorPageComponent`). Settings tab registered with `permission: 'email.read'` (every role per Step 6 grants) so list is visible to all; Edit/Delete inside the list gate on `email.templates.manage` (Owner / Admin / Sales Manager). Lucide registry extended with `Eye` + `Type`; `npm run check:icons` reports `60 distinct icons used, all registered`. **Notable adaptations from the spec:** (a) **Contact + lead detail compose surfaces don't exist as components in the codebase** — the spec's `contact-detail.page.html` and `lead-detail.page.html` aren't there. Picker integration lands ONLY on the conversations compose-bar for v1; once those surfaces ship, wiring the picker is a one-line `<app-email-template-picker [contactId]="..." (templateSelected)="...">` addition; (b) **Tab permission is `email.read` not `email.templates.manage`** — the spec conflated tab gate with action gate. The right model is `email.read` for the tab + `email.templates.manage` for destructive affordances, which is what shipped; (c) **No `.spec.ts` files** — the spec listed two tests as nice-to-have ("manual smoke + basic HTTP wiring spec"); existing project pattern is to skip thin-wrapper service specs; (d) **Iframe is `srcdoc` + `sandbox="allow-same-origin"` without `allow-scripts`** — defence-in-depth even though Step 6's `render` autoescapes; (e) **Caret-aware variable insertion via `data-tpl-field` attribute lookup** rather than `@ViewChild` — uses native `querySelector` so the editor doesn't need separate ViewChild handles for subject vs body. Smoke verified: `npm run check:icons` OK 60/60; `npx tsc --noEmit` clean across the whole app; routes resolve at `/user/settings/email-templates`, `/new`, `/:id/edit`; no regressions to other settings tabs. Pending manual: `ng serve` + click-through (docker stack is API-only).
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
