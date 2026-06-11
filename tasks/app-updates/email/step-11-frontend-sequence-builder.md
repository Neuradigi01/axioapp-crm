# Step 11 — Frontend: Sequence builder + enrollment UI from leads/contacts list

**Goal:** Org users can create multi-step email sequences in the UI, view enrollment status per sequence, and enroll leads/contacts in bulk from list pages. Per-lead status pill shows current step / paused / completed.
**Track:** App Updates → Email
**Status:** 11a COMPLETED · 11b PENDING — Per the spec's mandated 11a/11b split (17 files exceeds Rule-8 ceiling), this step ships in two halves. **11a (sequence library + builder + detail) is done**; **11b (bulk-enroll modal + per-lead status pill + wiring into list/detail pages) is queued**. 11a delivers: `app/src/app/features/user/core/services/email-sequences-api.service.ts` — typed CRUD (`listSequences` / `getSequence` / `createSequence` / `updateSequence` / `deleteSequence`) + enrollment ops (`enroll` / `listEnrollments` / `pauseEnrollment` / `resumeEnrollment` / `cancelEnrollment`) over `${apiBaseUrl}/email/sequences`. `sequence-list.component.ts/.html` is the settings-page tab — debounced 250ms name filter via `FormControl.valueChanges.pipe(debounceTime, distinctUntilChanged)`, table columns (Name → links to detail / Steps count / Enrollments compact stats / Updated via DatePipe / Actions), per-row stats are loaded lazily AFTER the main list resolves via three small `listEnrollments(size=1)` calls per row reading only the `total` field (workaround for the spec's assumed `/stats` endpoint which Step 7 didn't ship; bounded by visible-rows count); empty states for has-no-matches vs no-sequences-yet; soft-delete via DELETE with an inline confirm modal; Edit/Delete gated by `email.sequences.manage`. `sequence-builder.component.ts/.html` is the form — `FormControl` for name (required ≤255) + active toggle, plus a signal-driven step list (`steps = signal<BuilderStep[]>([])`) with HTML5 native drag-and-drop (no library): each step row carries `draggable="true"` + dragstart/dragover/dragleave/drop/dragend handlers, `draggingIndex` + `dropTargetIndex` signals drive the row visual states (opacity-50 on the source, blue border on the target), drop splices the array. Each step row has a step-1-immediate hint OR a numeric `delay_days` input (0–365), a remove button, and a template-picker popover that lazy-loads `EmailTemplatesApiService.list({q, is_active: true, size: 30})` with a 250ms debounced search and click-to-select. Save POSTs `createSequence` or PATCHes `updateSequence` with `steps[]` in array order (backend re-densifies `step_order` 1-based); 409 from PATCH when active enrollments exist surfaces as an inline error banner. `sequence-builder.page.ts` is the route shell (reads `:id` from `ActivatedRoute.snapshot.paramMap`, hands it to the builder as `input<string | null>` — `/new` resolves to null → create). `sequence-detail.component.ts/.html` is the standalone read+manage page — header with name + active pill + step summary (composed via `_cumulative` walking the dense `step_order` array, e.g. "day 0 → day 2 → day 7"), state-filter chips (all / active / completed / paused_on_reply / paused_manual / cancelled), enrollment table with state pill (emerald active / amber paused-on-reply / blue paused-manual / rose cancelled / zinc completed), current_step_order / total, enrolled_at via DatePipe, and per-row Pause / Resume / Cancel buttons (state-machine-aware via `canPause` / `canResume` / `canCancel` predicates; only one in-flight action at a time via `actingOn` signal; Cancel goes through `confirm()` because it's terminal). Three new routes added to `user.routes.ts`: `/settings/email-sequences` (tab), `/new`, `/:id/edit` (both → `SequenceBuilderPageComponent`), `/:id` (`SequenceDetailComponent`). Settings-page `TABS` extended with `id: 'email-sequences'` gated on `email.read` (everyone sees the list; the destructive actions inside gate on `email.sequences.manage`). Lucide registry extended in `app.config.ts` with `Workflow` + `Play` + `PauseCircle`; `npm run check:icons` reports `64 distinct icons used, all registered`. **Notable adaptations from the spec:** (a) **Stats endpoint not added to Step 7's router** — the spec's per-row "Active 12 · Completed 4 · Paused 1" comes from three lazy `listEnrollments(size=1)` calls per row that read the `total` field; bounded by the visible-rows count + only fires after the list resolves so the initial render isn't blocked. Cheap and good-enough for a settings page; a dedicated `/stats` endpoint can be added later if/when row counts climb; (b) **`?dry_run=true` enroll preview** is part of 11b — deferred along with the bulk-enroll modal that consumes it; (c) **No per-step send-log drawer** — the spec describes a drawer with per-step send timeline + open/click counts. v1 ships a flat enrollments table because the underlying `email_sequence_enrollment_steps` table doesn't have a list endpoint yet (Step 7 didn't expose one). Adding the drawer is straightforward once that endpoint lands; (d) **Drag-and-drop is HTML5 native, no library** — desktop-only as the spec acknowledges; touch reorder is post-v1; (e) **Tab permission is `email.read`**, not `email.sequences.manage` — same pattern as Step 10 templates: tab gate is "can browse", action gate is "can mutate"; (f) **Detail page is a standalone route**, not embedded in the settings tab — the enrollments table needs its own URL for deep-linking and the surface is too dense for tabbed content. Settings tab is just the list; detail / builder are separate pages. **11b pending work**: bulk-enroll modal (`enroll-bulk-modal.component.*`), enrollment-status pill (`enrollment-status-pill.component.*`), and wiring those into leads-list / contacts-list / lead-detail / contact-detail. Per the Step 10 audit, `contact-detail.page.html` and `lead-detail.page.html` don't exist as files — the pill will need to be plumbed once those pages ship. Smoke verified: `npm run check:icons` OK 64/64; `npx tsc --noEmit` clean across the whole app; routes resolve at `/user/settings/email-sequences`, `/new`, `/:id/edit`, `/:id`; no regressions to other settings tabs. Pending manual: `ng serve` + click-through.
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
