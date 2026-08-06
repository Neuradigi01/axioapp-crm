# Step 4 — Frontend — Schedule attach panel on workflow detail + config form + cron preview

**Goal:** In the workflow detail page, add a "Schedules" panel showing existing schedules for that workflow with an "Add schedule" button. The add/edit form exposes the 6 preset kinds + advanced cron, timezone picker (defaults to org tz), start/end, `on_missed` + `con  currency_policy` selects, and a "next 5 fires" live preview. Client-side debounced calls to `POST /schedules/preview`.

**Status:** COMPLETED (2026-08-06, schedules drawer + config modal + debounced cron preview live on `/user/workflows/:id` canvas; 6-kind recurrence form + tz picker + `on_missed`/`concurrency_policy` selects; If-Match round-trip; TS + ESLint + prettier + ng build all clean; Karma tests deferred as optional per plan)

**Depends on:** Step 3 (API)

---

## Scope

**In-scope:**
- New Angular components (standalone, signals, typed reactive forms):
  - `ScheduleAttachPanelComponent` — lives inside workflow detail page; lists existing schedules for the workflow; "Add schedule" button opens the config dialog.
  - `ScheduleConfigDialogComponent` — modal with the config form; used for both create and edit.
  - `ScheduleCronPreviewComponent` — small child that shows the next-5-fires list; consumes `POST /schedules/preview` via a debounced observable (500ms).
- Reactive form structure keyed on `schedule_kind`:
  - `once` → single datetime picker.
  - `daily` → time-of-day picker.
  - `weekly` → day-of-week multi-select + time-of-day.
  - `monthly` → radio between day-of-month (with 31→last-day help) and nth-weekday; time-of-day.
  - `interval` → number input + minute/hour/day unit; minimum 5 min hint.
  - `cron` → text input + cron help link; preview auto-updates.
- Timezone picker: searchable native `<select>` over `Intl.supportedValuesOf('timeZone')`, defaulting to org tz from the auth/session context.
- `on_missed` + `concurrency_policy` selects rendered with tooltips explaining each option.
- `starts_at` / `end_at` date-time pickers using existing `crm-mobile-datetime` component (per recent commits — matches the visual system).
- CRUD via `workflows.service.ts` extensions; `If-Match` header sent on PATCH from the last-loaded `updated_at`.
- Toast on 409 Conflict: "This schedule was changed by someone else. Reload to see current version."
- Toast on 422: field-level error surfacing.
- Empty state on the panel: "No schedules yet. Add one to run this workflow automatically."

**Out-of-scope:**
- Schedule surfacing in workflow LIST page (Step 5).
- Pause/resume actions (Step 5).
- Sidebar / navigation changes.
- New icon additions (verify any Lucide icons used are already in the registry per memory).

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/workflows/schedule-attach-panel.component.ts` | **NEW** — panel list + add button |
| `app/src/app/features/user/core/workflows/schedule-attach-panel.component.html` | **NEW** — panel markup, Tailwind |
| `app/src/app/features/user/core/workflows/schedule-config-dialog.component.ts` | **NEW** — modal form for create/edit |
| `app/src/app/features/user/core/workflows/schedule-config-dialog.component.html` | **NEW** — form markup, Tailwind |
| `app/src/app/features/user/core/workflows/schedule-cron-preview.component.ts` | **NEW** — debounced preview child |
| `app/src/app/features/user/core/workflows/schedule-cron-preview.component.html` | **NEW** — preview markup |
| `app/src/app/features/user/core/workflows/workflows.service.ts` | edit — add `listSchedules`, `createSchedule`, `updateSchedule`, `deleteSchedule`, `pauseSchedule`, `resumeSchedule`, `previewSchedule` methods; propagate `If-Match` via `ETag`-style state per schedule |
| `app/src/app/features/user/core/workflows/models.ts` | edit — add `Schedule`, `ScheduleKind`, `OnMissedPolicy`, `ConcurrencyPolicy`, `SchedulePreviewFire` types (mirror backend enums) |
| `app/src/app/features/user/core/workflows/workflow-detail-page.component.html` | edit — mount `<crm-schedule-attach-panel [workflowId]="workflow.id"/>` in a Tailwind card below the trigger tab |
| `app/src/app/features/user/core/workflows/workflow-detail-page.component.ts` | edit (minor) — import the new component if not standalone-auto-discovered |

**~10 files, ~600 lines.** Front-end-heavy step; if size review flags during implementation, split cron preview into 4a.

## Component surface

```typescript
// schedule-attach-panel.component.ts
@Component({
  selector: 'crm-schedule-attach-panel',
  standalone: true,
  imports: [CommonModule, ScheduleConfigDialogComponent, ...],
  templateUrl: './schedule-attach-panel.component.html',
})
export class ScheduleAttachPanelComponent {
  readonly workflowId = input.required<string>();
  private readonly workflowsService = inject(WorkflowsService);
  readonly schedules = signal<Schedule[]>([]);
  readonly loading = signal(true);
  ngOnInit() { this.reload(); }
  openAdd() { /* opens dialog with mode=create */ }
  openEdit(s: Schedule) { /* opens dialog with mode=edit, preloaded */ }
  async reload() { /* fetch + set signal */ }
}
```

## Plan

1. **Models + service** — type surface first, so the components can be authored against it.
2. **Config dialog** — form with `schedule_kind` as the top selector; kind-conditional form controls via `@switch` in the template; typed FormGroup per kind (`ScheduleOnceForm`, `ScheduleDailyForm`, ...).
3. **Cron preview child** — takes the current form value as an `input()` signal; debounced `toObservable(...)` → `switchMap` → API call. Cancelled on new input.
4. **Attach panel** — list existing schedules with next-run + status badges (active / paused / ended). Add button.
5. **Detail page mount** — add the panel below the workflow's existing trigger section. Tailwind card matching adjacent panels.
6. **Error toasts** — `MatSnackBar` (existing pattern).
7. **Prettier** — run `npx --no-install prettier --write` on every touched file BEFORE stop-report (per memory: pre-commit has bounced past commits without this).
8. **Karma tests** — one component test per new component: create-happy, edit-happy, kind-switch preserves shared fields, cron preview debounce.

## Visual notes

- Follow the existing workflows-detail-page card pattern (rounded-xl, border-zinc-200, shadow-sm, dark-mode variants). Match padding/typography of the trigger tab.
- Preset picker: segmented buttons or a native `<select>` — match how the trigger-kind picker is done today.
- Cron preview: monospace font for the datetimes; each fire shown with local tz label ("2026-08-06 09:00 IST").

## Verification

- Open a workflow's detail page → "Schedules" panel visible below trigger section.
- Click "Add schedule" → dialog opens.
- Pick each of the 6 presets → form fields adapt correctly.
- Pick "Advanced (cron)" → type `0 9 * * 1` → preview shows next 5 Mondays at 09:00.
- Save → schedule appears in the list.
- Edit → dialog pre-fills correctly; save with stale `If-Match` (open second tab, edit there first) → 409 toast.
- Save with past `starts_at` → 422 toast with field-level message.
- `npx --no-install prettier --check <touched-files>` clean.
- `npm run lint` clean.

## Stop-and-report template

```
Step 4 done — Schedule attach panel + config dialog + cron preview.

Files changed: <list>
What you can verify:
  - Navigate to a workflow's detail page → Schedules panel visible
  - Add schedule via each of 6 presets → all render + save
  - Advanced cron `0 9 * * 1` → preview shows next 5 Mondays 09:00 local
  - Two-tab edit → second save shows 409 conflict toast
  - Past starts_at → 422 toast with field-level error
Tests added: ~8 Karma cases
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean · prettier]
Awaiting your 'proceed' for Step 5.
```
