# Step 2.12 — Leads: frontend

**Goal:** Leads page with both Pipeline (kanban) and List views. New Lead modal uses `<app-dynamic-form>`. Status badges, source icons, INR budget formatting.
**Phase:** 2
**Depends on:** 2.11, 2.10, 2.3
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/leads/`:
  - `leads-api.service.ts`
  - `leads.page.ts/.html` — toggle between Pipeline and List tabs; filters (assigned_to, source, search).
  - `lead-card.component.ts/.html` — kanban card: name, phone, source icon, budget INR, stage badge.
  - `lead-form-modal.component.ts/.html` — Standard fields (contact picker / new contact, budget, expected_close_date, assigned_to) + `<app-dynamic-form>` for custom.
- INR formatter pipe `formatINR`.
- Tailwind only.

**Out of scope:**
- Bulk actions / import — later.

## Files to touch
- `app/src/app/features/user/core/leads/*` (created)
- `app/src/app/features/user/core/shared/pipes/inr.pipe.ts` (created)
- `app/src/app/app.routes.ts` (modified)

## Plan
1. API service.
2. Page: pipeline view feeds `<app-pipeline-board pipelineKey="leads" [items]="leads()" itemTemplate=lead-card>`; on `(itemMoved)` calls move-stage endpoint, optimistic update, revert on error.
3. List view: table.
4. New Lead modal: contact-picker autocomplete (search contacts by name/phone) + "create new" inline; standard fields; dynamic-form for custom fields with entity_type=`lead`.
5. INR pipe: `Intl.NumberFormat('en-IN', {style:'currency',currency:'INR'})`.

## Verification checklist
**Frontend:**
- visit `/leads` → kanban with stages (after pack install in 4.2).
- create lead → appears in `new` column.
- drag to `contacted` → persists.
- toggle to List → table shows same data.

## Self-check (10 rules)
- [ ] Form fields dynamic (rule 4).
- [ ] No imports from packs.
- [ ] Tailwind only.

## Stop & report
Await "proceed" before Step 2.13.
