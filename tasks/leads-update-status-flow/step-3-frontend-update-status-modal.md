# Step 3 — Frontend: `UpdateStatusModal` component + lead-detail header button + `logUpdate` FE API

**Goal:** Add sir's compact quick-status modal to the lead detail page. Opens from a new "Update Status" button in the header (alongside Edit and Delete), presents contact-basics + stage + status + source + remarks + next-follow-up datetime + follow-up type, POSTs to `/leads/{id}/log-update` from step 1, and refreshes the lead view on success.
**Track:** Leads — Update Status Flow
**Status:** Pending
**Depends on:** Step 1 (`POST /leads/{id}/log-update` endpoint).

---

## Scope

In-scope:

- New standalone Angular component `UpdateStatusModalComponent` with reactive form.
- Fields: Name / WhatsApp / Email (contact-basics — narrow), Source dropdown, Category (pipeline stage) dropdown, Status dropdown (derived, read-only when stage is Won/Lost, editable otherwise), Remarks textarea (required, 1–2000 chars), Next Follow-Up datetime + follow-up type dropdown (call/whatsapp/email/document/meeting/other).
- Fields render with the floating-label outlined style from sir's screenshot.
- Inline validation errors under each field (same convention as the SMTP sender modal fixed earlier: `@if (control.touched && control.invalid)` red text).
- `Close` (secondary) + `Update Profile` (primary) buttons. `Update Profile` disabled until form valid; shows spinner while POSTing.
- Optimistic guard: modal captures `pipeline_stage` on open and sends it as `if_current_stage`. On 409 → modal shows a red banner ("The lead was updated by someone else. Refresh and try again.") and disables the button.
- Shared-contact block: if the response is 422 `contact_shared` → modal disables the three contact fields and shows a helper line ("This customer is on N leads — [Edit from contacts page]" as a link). Rep can still submit the rest.
- On success: emit `saved` event with the refreshed lead, parent closes modal + updates the header pills.
- New `logUpdate(leadId, payload)` method on `LeadsApiService`.
- New "Update Status" button on lead-detail header (primary accent color, positioned left of Edit).
- Modal opens with lead's current stage/status/source pre-selected. Contact-basics pre-filled from the linked contact. Next Follow-Up defaulted to tomorrow 10:00 in the user's local TZ (Architect LOW: no year-1950 defaults).

Out of scope:

- No changes to the existing `lead-form-modal` (full editor). Sir's ask is additive.
- No follow-up history table (step 4).
- No Leads Center toolbar (step 5).
- No inline row-level "Update Status" from the leads list (deferred — reachable via row click → detail → button).
- No call-disposition / duration / outcome fields (Architect HIGH #2 — separate future track).

## DB changes / migrations

**None.** Frontend only.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/leads/update-status-modal.component.ts` | created |
| `APP/src/app/features/user/core/leads/update-status-modal.component.html` | created |
| [`APP/src/app/features/user/core/leads/lead-detail.page.ts`](../../APP/src/app/features/user/core/leads/lead-detail.page.ts) | modified — wire the button state signal + open/close/save handlers |
| [`APP/src/app/features/user/core/leads/lead-detail.page.html`](../../APP/src/app/features/user/core/leads/lead-detail.page.html) | modified — add the button in header + `<app-update-status-modal>` block |
| [`APP/src/app/features/user/core/leads/leads-api.service.ts`](../../APP/src/app/features/user/core/leads/leads-api.service.ts) | modified — add `logUpdate(leadId, payload): Observable<LogUpdateResponse>` |

**5 files, ~450 LOC.** Just above the ~400 soft ceiling; if it grows past 500 during implementation, split the modal template into a partial and re-count.

## Plan

1. **API method.** Add `logUpdate(leadId, payload)` on `LeadsApiService` that POSTs to `/leads/${leadId}/log-update`. Payload interface matches the backend `LogUpdateRequest`. Response interface matches `LogUpdateResponse` (refreshed `Lead` + optional `next_follow_up_task_id`).
2. **Modal component skeleton.** Standalone, `ChangeDetectionStrategy.OnPush`, `imports: [ReactiveFormsModule, LucideAngularModule, MobileSelectComponent]`. Inputs: `lead: Lead` (signal-input), `pipelineStages: PipelineStage[]` (signal-input). Outputs: `cancelled: EventEmitter<void>`, `saved: EventEmitter<Lead>`.
3. **Form shape.**
   ```ts
   interface FormShape {
     contact_full_name: FormControl<string>;
     contact_phone: FormControl<string>;
     contact_email: FormControl<string>;
     source: FormControl<LeadSource>;
     pipeline_stage: FormControl<string>;  // Category
     status: FormControl<LeadStatus>;      // derived, disabled when stage is won/lost
     remarks: FormControl<string>;
     next_follow_up_at: FormControl<string>;  // ISO datetime-local input
     next_follow_up_type: FormControl<TaskFollowupType>;
   }
   ```
   Validators — mirror backend: `remarks` required + max 2000; `next_follow_up_at` bounded to now-1y .. now+5y; `pipeline_stage` must be one of the org's stage keys.
4. **Signal wiring.** Isolate `form.statusChanges` → signal via `toSignal()` (fix pattern from the SMTP modal): `formValid = computed(() => this.formStatus() === 'VALID')`. Otherwise the submit button won't enable — same bug I hit last session.
5. **Preload.** In `constructor` / `ngOnInit`, `form.reset({ ...lead's current values, next_follow_up_at: <tomorrow 10:00 local> })`. Contact-basics come from `lead.contact` if the detail page has it hydrated, else emit a signal to the parent to fetch.
6. **Auto-derive status from stage.** `effect(() => { const stage = this.pipelineStages().find(s => s.key === this.form.value.pipeline_stage); if (stage?.is_won) form.controls.status.setValue(LeadStatus.WON); if (stage?.is_lost) LOST; else ACTIVE; })`. Disable status control unless the derived value doesn't match one of the automatic mappings (edge case — rep manually setting Active on a Won stage).
7. **Submit handler.** Build payload from form; call `api.logUpdate(lead.id, payload)`. On success emit `saved`. On 409 → set optimistic-guard error signal. On 422 with `detail=contact_shared` → set shared-contact error, disable the contact controls, keep the modal open. On other errors → generic red banner with the API error message.
8. **Template.** Mirror sir's screenshot layout: 2-column grid on desktop (`sm:grid-cols-2`), collapses to single column on mobile. Floating-label style. Inline error `<p class="mt-1 text-xs text-red-500">` under each field, gated by `@if (control.touched && control.invalid)`. Use `crm-mobile-select` for every dropdown (matches app-wide convention set last session for the SMTP modal). Datetime input: `<input type="datetime-local">` — browser handles the picker cleanly + matches sir's screenshot.
9. **Header button.** In `lead-detail.page.html`, add a green/accent button "Update Status" positioned left of Edit. Wire click to a signal `updateStatusOpen.set(true)`. Render `<app-update-status-modal>` inside an `@if (updateStatusOpen())` block, passing the current `lead()` and pipelineStages, with `(cancelled)="updateStatusOpen.set(false)"` and `(saved)="onLeadSaved($event)"`.
10. **`onLeadSaved` handler.** Set `lead.set(updated)`; `updateStatusOpen.set(false)`. If `saved` event also carries `next_follow_up_task_id`, prepend the new task in step 4's follow-up panel via a viewChild ref (do that in step 4).

## Tests

Unit (Vitest / Angular TestBed):

1. **Form disables submit when invalid.** Empty `remarks` → `Update Profile` disabled. Fill it in + valid `pipeline_stage` → enabled.
2. **Signal-based validity fires on typing** (regression from the SMTP modal `computed(() => form.valid)` bug — assert `formStatus` signal updates on `form.controls.remarks.setValue('x')`).
3. **Status auto-derives from stage.** Setting `pipeline_stage` to a won stage → `status` control value = `WON` and disabled.
4. **Preload uses tomorrow-10am default.** Component instantiation with a lead that has no next task → `next_follow_up_at` control equals tomorrow 10:00 in local TZ.
5. **Submits the right payload shape.** Mock `api.logUpdate`; verify called once with `if_current_stage = lead.pipeline_stage` (captured at open), no extra fields.
6. **409 → shows optimistic-guard banner and disables submit.**
7. **422 `contact_shared` → disables contact controls, shows helper.**
8. **`saved` event fires the refreshed lead on 200.**
9. **`cancelled` event fires on backdrop click and Close button.**

Manual smoke (browser):

10. Open a lead in Ajay's Workspace. Click "Update Status." Modal opens with pre-filled values. Change stage from Proposal to Qualified, add remarks, set follow-up to tomorrow 2pm, choose "Call." Click Update Profile. Modal closes; header stage pill updates to Qualified. Refresh page → still Qualified. Open Activities tab → new note and status_change rows visible. Dashboard "Today's Follow-ups" → new task not shown (due tomorrow, not today), but "Pending" bucket count incremented.

## Smoke

```powershell
# Run the frontend (in APP/)
cd APP; npm start

# Browse to a lead (Neuradigi in Ajay's org — org 41f9ede9-41b3-44ce-b489-3004566d4068)
# http://localhost:4200/user/leads/<neuradigi-id>

# Manual click-through per test #10 above.

# Format before commit (memory rule)
npx --no-install prettier --write src/app/features/user/core/leads/update-status-modal.component.ts src/app/features/user/core/leads/update-status-modal.component.html src/app/features/user/core/leads/lead-detail.page.ts src/app/features/user/core/leads/lead-detail.page.html src/app/features/user/core/leads/leads-api.service.ts
```

## Risks

- **Datetime-local input timezone.** Browser sends the datetime in the user's local TZ but without offset. Convert to UTC ISO string on submit (use `new Date(value).toISOString()`); backend stores UTC. Document the round-trip: on preload, convert the lead's `next_follow_up_at` (UTC ISO) back to local for the input value using `toLocaleString('sv')` or a small helper.
- **`crm-mobile-select` datetime option.** The mobile-select component only handles `MobileSelectOption` (value/label). Follow-up-type picker uses it (6 known values). Datetime uses native `<input type="datetime-local">`. Consistent with the pattern already accepted in the app.
- **Preload race.** If the modal opens before the pipeline stages resolve, the Category dropdown is empty. Guard: `@if (pipelineStages().length > 0)` around the form; show a small skeleton while empty.
- **Third header button UX.** Architect flagged as smell (README rejected list — deferred). If reps report confusion, revisit by moving Edit into a `…` overflow menu.

## Rollback

Revert the five files. No DB state affected.
