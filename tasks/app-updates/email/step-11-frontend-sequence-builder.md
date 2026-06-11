# Step 11 — Frontend: Sequence builder + enrollment UI from leads/contacts list

**Goal:** Org users can create multi-step email sequences in the UI, view enrollment status per sequence, and enroll leads/contacts in bulk from list pages. Per-lead status pill shows current step / paused / completed.
**Track:** App Updates → Email
**Status:** Pending
**Depends on:** Step 7 (sequences backend), Step 10 (template picker reusable).

---

## Scope

In-scope:

- New page `/user/settings/email-sequences` (list + detail).
- Components:
  - `sequence-list.component.ts/.html` — table: name, # steps, active enrollments, completed enrollments, paused (reply), created-by, actions.
  - `sequence-builder.component.ts/.html` — ordered step editor: each step row picks a template (reuses Step 10's picker) + sets `delay_days`. Drag-handle reorder (HTML5 DnD; no library). Save persists the whole sequence in one transaction.
  - `sequence-detail.component.ts/.html` — shows enrollment list filterable by state. Click an enrollment row → drawer with the per-step send log + open/click counts.
  - `enroll-bulk-modal.component.ts/.html` — reusable modal mounted from leads-list + contacts-list "bulk action" menu. Picks a sequence, shows selected-count, preview of "will skip N already-enrolled". Confirm enrolls.
  - `enrollment-status-pill.component.ts/.html` — small badge for the lead/contact detail page showing "In sequence X, step 2/3, next send in 1 day" or "Paused on reply".
- `email-sequences-api.service.ts` — sequence CRUD + enrollment ops.
- Wire bulk-action menu in leads-list + contacts-list (already has the bulk-action pattern from contacts).
- Wire status-pill into lead-detail + contact-detail pages.
- Tailwind only.

Out of scope:

- Branching sequences UI — backend doesn't support (Step 7).
- A/B testing UI — same reason.
- Enrollment-from-pipeline-stage-transition automation — that's a workflow feature, separate track (post-v1).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/email-sequences/sequence-list.component.ts` | created |
| `app/src/app/features/user/core/settings/email-sequences/sequence-list.component.html` | created |
| `app/src/app/features/user/core/settings/email-sequences/sequence-builder.component.ts` | created |
| `app/src/app/features/user/core/settings/email-sequences/sequence-builder.component.html` | created |
| `app/src/app/features/user/core/settings/email-sequences/sequence-detail.component.ts` | created |
| `app/src/app/features/user/core/settings/email-sequences/sequence-detail.component.html` | created |
| `app/src/app/features/user/core/shared/email/enroll-bulk-modal.component.ts` | created |
| `app/src/app/features/user/core/shared/email/enroll-bulk-modal.component.html` | created |
| `app/src/app/features/user/core/shared/email/enrollment-status-pill.component.ts` | created |
| `app/src/app/features/user/core/shared/email/enrollment-status-pill.component.html` | created |
| `app/src/app/features/user/core/services/email-sequences-api.service.ts` | created |
| `app/src/app/features/user/user.routes.ts` | modified — add `/user/settings/email-sequences` + `/new` + `/:id` |
| `app/src/app/features/user/core/leads/leads-list.page.html` | modified — bulk-action "Enroll in sequence" |
| `app/src/app/features/user/core/contacts/contacts-list.page.html` | modified — same |
| `app/src/app/features/user/core/leads/lead-detail.page.html` | modified — mount enrollment-status-pill |
| `app/src/app/features/user/core/contacts/contact-detail.page.html` | modified — mount enrollment-status-pill |
| `app/src/app/app.config.ts` | modified — register lucide icons (`workflow`, `play`, `pause-circle`, `check-circle-2`) |

**17 files.** This exceeds the rule-8 ceiling. **Split into 11a (builder + detail UI, ~9 files) and 11b (bulk enrollment + status pill, ~8 files)** before starting work.

## Plan (11a — sequence builder + detail)

1. Service: typed client for all sequence + enrollment endpoints.
2. Sequence-builder: step rows are signal-driven; each row owns `{template_id, delay_days}`. Add step appends. Drag-reorder updates `step_order` indexes. Save POSTs or PATCHes the full sequence.
3. Sequence-list: table with debounced name filter; per-row metrics ("Active 12 • Completed 4 • Paused on reply 1") fetched from a `/sequences/{id}/stats` summary endpoint added in Step 7.
4. Sequence-detail: header with the sequence name + step summary; below, a filterable enrollment table (state filter + contact-name filter). Row click opens a drawer with per-step send timeline.
5. Routes + settings-tab link + lucide icons.

## Plan (11b — bulk enrollment + status pill)

1. `enroll-bulk-modal`: receives a list of contact-ids OR lead-ids from the parent. Picker for sequence. Preview call to `/sequences/{id}/enroll?dry_run=true` (add `dry_run` to Step 7 router) shows "Will enroll 18, skip 2 already enrolled". Confirm hits the real endpoint.
2. `enrollment-status-pill`: subscribes to `/enrollments?contact_id=` filtered to active enrollments. Renders compact badge with next-send countdown. Click opens a small popover with sequence name + step + pause button.
3. Wire bulk-action menus in the two list pages.
4. Wire pill into the two detail pages.

## Tests

- `email-sequences-api.service.spec.ts` — HTTP wiring.
- `enroll-bulk-modal.component.spec.ts` — dry-run preview displays counts; confirm calls real endpoint.
- `sequence-builder.component.spec.ts` — drag-reorder updates step_order; save serialises correctly.

## Smoke

```powershell
cd app
npm run start

# As Owner:
# /user/settings/email-sequences → empty
# Create "Designer outreach" with 3 steps (delay 0, 2, 5 days) using pre-saved templates
# Save → list shows new sequence

# /user/leads → select 5 leads → "Bulk actions" → "Enroll in sequence"
# Pick sequence; preview "Will enroll 5". Confirm.
# Leads page: each lead row now shows status pill "In Designer outreach, step 1/3"

# Advance simulated time via the celery beat (or use the `/sequences/{id}/test-tick` dev endpoint if added)
# Step 1 fires; pill updates to step 2/3; activity row appears on each lead

# Simulate inbound reply on one lead (or test by replying for real from the Gmail account)
# Within ~60s, pill updates to "Paused on reply" for that lead
```

## Risks

- **17-file step.** Already flagged — split into 11a + 11b. Per Rule 8.
- **Drag-and-drop on touch devices.** HTML5 DnD is desktop-only friendly. If touch support matters for sequence reordering, swap to a long-press handler; not blocking for v1 since sequence editing is admin-side and rarely done on mobile.
- **Pill polling cost.** Pills on a 50-row leads list polling every 30s is 50 HTTP calls/30s. Mitigation: fetch in one batched call per page load via `/enrollments?contact_ids=…` and store in a small map signal; re-fetch only on tab focus, not interval.

## Rollback

Delete files. Revert user.routes.ts + the four list/detail page templates + app.config.ts. Backend sequences keep running for any in-flight enrollments — the UI just disappears.
