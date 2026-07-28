# Step 4 — Activity & action forms (tasks, appointments, calls, reviews, notes)

**Goal:** Apply shared validators to the six modals that create activities against existing records — tasks, book/reschedule appointments, log call, reply to review, add note — so every activity carries clean, bounded data.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** COMPLETED — 6 activity/action modals wired to shared validators. Step 1's shared-validator file extended with 4 more helpers (`dateWithinPastDays`, `fileUploadValidator`, `trimmedRequired`, `picklistValidator`); `commonValidators` and `DEFAULT_MESSAGES` extended. Log-call refactored to use the shared file-upload validator (drops the local extension/size checks). Reschedule modal gained a cross-field check that rejects "new time same as original" and past times. Reply-modal and add-note now reject whitespace-only text and enforce min 2 chars. tsc + eslint + prettier all clean; 4 pre-existing eslint warnings unrelated to this step.
**Depends on:** Step 1 (shared validators).

---

## Scope

Six component files. Same in-place pattern as Step 3 — control-array edits + template error strings, no logic or layout changes.

Files:

1. `app/src/app/features/user/core/tasks/task-form-modal.component.ts`
2. `app/src/app/features/user/core/appointments/book-appointment-modal.component.ts`
3. `app/src/app/features/user/core/appointments/reschedule-modal.component.ts`
4. `app/src/app/features/user/core/calls/log-call-modal.component.ts`
5. `app/src/app/features/user/core/reviews/reply-modal.component.ts`
6. `app/src/app/features/user/core/activities/add-note.component.ts`

## Per-form changes

### Task form modal

| Field | Before | After |
|---|---|---|
| `title` | `commonValidators.required`, `commonValidators.maxLength(255)` | unchanged |
| `description` | (override-driven) | `commonValidators.maxLength(2000)` when present |
| `priority` | `commonValidators.required` | unchanged |
| `due_at` | (override-driven) | `dateNotPast` when required — allow past for retrospective task logging only if the form has an explicit "log historical" toggle (there isn't one; block past) |
| `followup_type` | (no validator) | value must be in server-provided options — enforced by picklist validator (added in Step 1) |
| `assigned_to_id` | (override-driven) | unchanged (uuid-shaped selector, already validated by the picker) |

### Book appointment modal

| Field | Before | After |
|---|---|---|
| `title` | `commonValidators.required`, `commonValidators.maxLength(255)` | unchanged |
| `scheduled_at` | `commonValidators.required` | add `dateNotPast` |
| `duration_min` | `commonValidators.required` | add `Validators.min(1)`, `Validators.max(1440)` explicitly (not just via override) |
| `purpose` / `location` | (override-driven) | `commonValidators.maxLength(1000)` each |
| `assigned_to_id` | required | unchanged |

### Reschedule modal

Same fields as Book — apply identical validators. Additionally add a cross-field check that the new `scheduled_at` differs from the original (prevents accidental empty reschedule).

### Log call modal

| Field | Before | After |
|---|---|---|
| `direction` | `Validators.required` | unchanged |
| `started_at` | (none) | ISO datetime pattern; add `dateNotPast` — but relax for calls (calls are logged *after* they happen, so accept past up to 30 days back) → new validator `dateWithinPastDays(30)` added in Step 1 |
| `duration_seconds` | (none) | `Validators.min(0)`, `Validators.max(86400)` (24 hours) |
| `outcome_id` | (none) | picklist validator |
| `recording_file` | 30 MB + extension whitelist (already enforced in code) | move enforcement into a shared `fileUploadValidator({maxMb: 30, exts: ['mp3','m4a','ogg','wav']})` — added to Step 1's frontend validator set |
| `notes` | (none) | `commonValidators.maxLength(4000)` |

### Reply modal (review)

| Field | Before | After |
|---|---|---|
| `text` | `Validators.required`, `Validators.minLength(1)` | `Validators.required`, `Validators.minLength(2)`, `Validators.maxLength(4000)` |

### Add note

| Field | Before | After |
|---|---|---|
| `text` | `Validators.required`, `Validators.maxLength(4000)` | `Validators.required`, `Validators.minLength(2)`, `Validators.maxLength(4000)` |

Both `reply-modal` and `add-note` should trim before submit (existing code does this manually; move it into a `trimmedRequired` shared validator so blank-whitespace inputs are rejected consistently).

## New shared validators added under Step 1's foundation

Two small additions to `app/src/app/shared/validators/custom-validators.ts` that Step 1 lists in scope but this step first consumes:

- `dateNotPast(control)` — rejects ISO date/datetime values earlier than "now" (with a 5-minute grace window for clock skew).
- `dateWithinPastDays(n)` — factory; accepts past dates within `n` days, rejects earlier.
- `fileUploadValidator({maxMb, exts})` — factory; checks File.size + extension.
- `trimmedRequired(control)` — required + rejects whitespace-only.

If any of these were missed in Step 1, add them here before moving on.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/tasks/task-form-modal.component.ts` | modified |
| `app/src/app/features/user/core/tasks/task-form-modal.component.html` | modified — error messages |
| `app/src/app/features/user/core/appointments/book-appointment-modal.component.ts` | modified |
| `app/src/app/features/user/core/appointments/book-appointment-modal.component.html` | modified |
| `app/src/app/features/user/core/appointments/reschedule-modal.component.ts` | modified |
| `app/src/app/features/user/core/calls/log-call-modal.component.ts` | modified |
| `app/src/app/features/user/core/calls/log-call-modal.component.html` | modified |
| `app/src/app/features/user/core/reviews/reply-modal.component.ts` | modified |
| `app/src/app/features/user/core/activities/add-note.component.ts` | modified |
| `app/src/app/shared/validators/custom-validators.ts` | modified — 4 additional validators if not already in from Step 1 |

**~10 files.** At the ceiling. If the shared-validator additions add more than a few lines, defer some to Step 5 to stay under budget.

## Tests

Extend colocated specs where they exist:

- Task modal: past `due_at` rejected.
- Book appointment: past `scheduled_at` rejected; `duration_min = 0` rejected; `duration_min = 1441` rejected.
- Log call: `started_at` earlier than 30 days ago rejected; recording file `.exe` rejected; recording > 30 MB rejected.
- Reply / add-note: `"   "` (whitespace only) rejected via `trimmedRequired`.

## Smoke

```
# Manual browser walk against Ajay's Workspace:
# 1. /user/tasks → "New task" → due date "yesterday" → inline error.
# 2. /user/appointments → "Book" → scheduled_at yesterday → error; duration 0 → error.
# 3. /user/appointments/<id> → Reschedule → try same original time → cross-field error.
# 4. Contact detail → "Log call" → recording upload of "test.exe" → error.
# 5. Any review → "Reply" → submit with whitespace only → error.
# 6. Contact detail → "Add note" → submit with whitespace only → error.
```

## Risks

- **Historical call logging** — 30-day past-window may be too tight for some workflows. Confirm with the user during kickoff; if 90 days is safer, adjust the factory arg.
- **Clock skew on `dateNotPast`** — 5-minute grace covers common cases (server slightly ahead of client). If a user's laptop clock is > 5 minutes off, they'll see a false error. Acceptable.
- **Existing tasks with past `due_at`** — untouched. New saves validate; existing rows only re-validate when the user opens the modal to edit.

## Rollback

Revert the ~10 files.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Custom fields on these modals validate via dynamic-form (Step 1).
- ✅ Rule 4: Dynamic-form rendering unchanged.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: ≤ 10 files, small changes each.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs.
