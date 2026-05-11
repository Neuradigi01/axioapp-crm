# Step 2.7 — Activities timeline: frontend

**Goal:** Reusable `<app-activity-timeline>` component. Plug into Contact detail Activities tab. Manual "Add Note" action.
**Phase:** 2
**Depends on:** 2.6, 2.5
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/activities/`:
  - `activities-api.service.ts`
  - `activity-timeline.component.ts/.html` — input `(entityType, entityId)`, fetches and renders timeline grouped by day. Type icon + label + relative time + payload.
  - `add-note.component.ts/.html` — small textarea + submit; refreshes timeline.
- Plug into Contacts detail's Activities tab.
- Tailwind only.

**Out of scope:**
- Notes vs Tasks separation — 2.8.

## Files to touch
- `app/src/app/features/user/core/activities/*` (created)
- `app/src/app/features/user/core/contacts/contact-detail.page.html` (modified)

## Plan
1. API service.
2. Timeline component: fetch on init + on `entityId` change. Render a vertical line with circle icons.
3. Type → icon map: call=phone, note=note, email=mail, whatsapp=message, status_change=arrow-right, task=check.
4. Relative time via a small pure pipe.
5. Add-note: form, submit calls POST then prepends to list.

## Verification checklist
**Frontend:**
- visit a contact → Activities tab → empty state initially.
- add note → appears at top.

## Self-check (10 rules)
- [ ] No imports from `packs/`.
- [ ] Component reusable: takes only `entityType` + `entityId`; will be used by Leads, Walk-ins later.

## Stop & report
Await "proceed" before Step 2.8.
