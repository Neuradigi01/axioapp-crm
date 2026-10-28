# Step 2.5 — Contacts: frontend

**Goal:** Contacts list page (table view) + contact detail page with tabs (Overview, Activities, Notes, Tasks — last three are placeholders until 2.6/2.7/2.8). New/edit forms use `<app-dynamic-form>` fed by `/custom-fields/contact/render`.
**Phase:** 2
**Depends on:** 2.4, 2.3, 1.10
**Status:** COMPLETED

## Scope
**In-scope:**
- `app/src/app/features/user/core/contacts/`:
  - `contacts-api.service.ts`
  - `contacts-list.page.ts/.html` — table with search, source filter, tag filter, pagination.
  - `contact-detail.page.ts/.html` — header (avatar, name, phone, email), tabs.
  - `contact-form-modal.component.ts/.html` — wraps `<app-dynamic-form>` plus the system fields (full_name, phone, email, source, tags).
- Routes: `/contacts`, `/contacts/:id`.
- The system-vs-custom distinction in the form: a top "Standard" section (full_name, phone, email, source, tags) + a "Custom" section rendered by `<app-dynamic-form>` with the rendered field defs.
- Tailwind only.

**Out of scope:**
- Activities tab body — 2.7.
- Notes/Tasks tab body — 2.8.

## Files to touch
- `app/src/app/features/user/core/contacts/*` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. API service + signal store for list page.
2. List page: search input, filter chips, table with columns (Name, Phone, Email, Source, Tags). Click row → detail.
3. Form modal: split standard vs custom. On open, fetch render fields. On submit, merge into payload.
4. Detail page tabs: Overview shows formatted standard + custom fields; placeholders for the other three tabs.
5. Loading + empty states (Tailwind skeletons).

## Tests to add
- None (skipTests). Manual smoke per checklist.

## Verification checklist
**Frontend:**
- visit `/contacts` → list renders.
- click "New Contact" → form has Standard + Custom sections; custom field "DOB" appears (from 2.4 seed).
- create + view detail → fields shown.
- search by name → list narrows.

## Self-check (10 rules)
- [ ] Form fields rendered dynamically from API (rule 4).
- [ ] No hardcoded custom field UI.

## Stop & report
Await "proceed" before Step 2.6.
