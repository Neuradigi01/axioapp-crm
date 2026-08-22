/**
 * Update-Status modal. Opens from the "Update Status" button on the
 * lead-detail header (alongside Edit / Delete). Presents contact-basics
 * (name / phone / email) + Source + Category (pipeline stage) + Status
 * + Remarks + Next Follow-Up datetime + follow-up type in one compact
 * form; on submit calls `LeadsApiService.logUpdate()` which lands the
 * whole modal state atomically on the backend (see
 * `tasks/leads-update-status-flow/step-1-backend-log-update-endpoint.md`).
 *
 * Emits:
 *  - `saved({ lead, next_follow_up_task_id })` — refreshed lead + id
 *    of the newly-created follow-up task (or null).
 *  - `cancelled` — Close button, backdrop click, Escape.
 *
 * `if_current_stage` is captured on modal open and shipped on submit
 * so the backend's optimistic-lock guard fires 409 when a colleague
 * moved the stage in the meantime — we surface that as a red banner
 * rather than clobbering their move with fabricated history.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { Contact } from '../contacts/contacts-api.service';
import { PipelineStage } from '../pipelines/pipelines-api.service';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
import { UserMini, UsersDirectoryService } from '../shared/services/users-directory.service';
import { commonValidators } from '../shared/validators';
import { LeadFollowUpsPanelComponent } from './lead-follow-ups-panel.component';
import {
  Lead,
  LeadSource,
  LeadsApiService,
  LogUpdateRequest,
  NextFollowUpSpec,
} from './leads-api.service';

type FollowUpType = NextFollowUpSpec['followup_type'];

interface FormShape {
  contact_full_name: FormControl<string>;
  contact_phone: FormControl<string>;
  contact_email: FormControl<string>;
  source: FormControl<LeadSource>;
  /** Renamed in the UI as "Status" per sir's ask — the dropdown lists
   *  the org's pipeline stages (proposal / qualified / won / lost /
   *  etc.). Server maps stage → `LeadStatus` (active/won/lost) inside
   *  `log_update_for_lead` so the FE doesn't ship a redundant `status`
   *  field. */
  pipeline_stage: FormControl<string>;
  /** Owner (assignee) — empty string = "Unassigned". The modal opens
   *  pre-selected with the lead's current owner; the submit builder
   *  emits `set_assigned_to=true` + `assigned_to_id` only when the
   *  value differs from the loaded lead, so a rep who just wanted to
   *  add a note doesn't inadvertently touch ownership. */
  assigned_to_id: FormControl<string>;
  remarks: FormControl<string>;
  next_follow_up_at: FormControl<string>;
  next_follow_up_type: FormControl<FollowUpType>;
  lost_reason: FormControl<string>;
  lost_reason_other: FormControl<string>;
}

const SOURCE_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'manual', label: 'Manual' },
  { value: 'walk_in', label: 'Walk-in' },
  { value: 'widget', label: 'Web form' },
  { value: 'google_ads', label: 'Google Ads' },
  { value: 'meta_ads', label: 'Meta Ads' },
  { value: 'whatsapp_flow', label: 'WhatsApp' },
  { value: 'bulk_import', label: 'Bulk import' },
];

const FOLLOWUP_TYPE_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'call', label: 'Call' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'meeting', label: 'Meeting' },
  { value: 'document', label: 'Document' },
  { value: 'other', label: 'Other' },
];

/** Matching backend validator bounds so users see the same error the
 *  server would return — no round-trip needed for the obvious cases. */
const REMARKS_MAX = 2000;
const FOLLOWUP_LOOKBACK_DAYS = 365;
const FOLLOWUP_LOOKAHEAD_DAYS = 5 * 365;

/** Lost-reason picklist mirrors ``LOST_REASONS`` in
 *  ``API/src/app/core/leads/schemas.py``. */
const LOST_REASON_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: '', label: '— Choose a reason —' },
  { value: 'price', label: 'Price' },
  { value: 'timing', label: 'Timing' },
  { value: 'competitor', label: 'Competitor' },
  { value: 'no_response', label: 'No response' },
  { value: 'other', label: 'Other' },
];

@Component({
  selector: 'app-update-status-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    ReactiveFormsModule,
    MobileSelectComponent,
    LeadFollowUpsPanelComponent,
  ],
  templateUrl: './update-status-modal.component.html',
})
export class UpdateStatusModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(LeadsApiService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly destroyRef = inject(DestroyRef);

  /** Org user roster — feeds the Owner dropdown + is consulted for the
   *  "Reassigned from Ravi to Priya." auto-remark string. Cached
   *  session-wide by the directory service; empty array on failure. */
  protected readonly orgUsers = signal<UserMini[]>([]);
  protected readonly ownerOptions = computed<MobileSelectOption[]>(() => [
    { value: '', label: '— Unassigned —' },
    ...this.orgUsers()
      .slice()
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
      .map((u) => ({ value: u.id, label: u.full_name || u.email })),
  ]);

  private ownerLabel(id: string | null): string {
    if (!id) return 'Unassigned';
    const hit = this.orgUsers().find((u) => u.id === id);
    return hit ? hit.full_name?.trim() || hit.email : 'Unassigned';
  }

  readonly lead = input.required<Lead>();
  readonly contact = input<Contact | null>(null);
  readonly pipelineStages = input.required<PipelineStage[]>();

  readonly cancelled = output<void>();
  readonly saved = output<{ lead: Lead; next_follow_up_task_id: string | null }>();

  protected readonly submitting = signal(false);
  /** Distinguishes the 409 optimistic-guard error (special banner +
   *  disable-submit) from the generic per-field / network error. */
  protected readonly stageDriftedTo = signal<string | null>(null);
  /** Non-null → the underlying contact is on >1 leads and the backend
   *  refused the contact-basics patch. We surface a helper line + gray
   *  out the three contact controls; the rest of the submit still
   *  works when the rep clears the contact fields. */
  protected readonly sharedContactCount = signal<number | null>(null);
  protected readonly errorBanner = signal<string | null>(null);

  protected readonly sourceOptions = SOURCE_OPTIONS;
  protected readonly followupTypeOptions = FOLLOWUP_TYPE_OPTIONS;
  protected readonly lostReasonOptions = LOST_REASON_OPTIONS;

  protected readonly stageOptions = computed<MobileSelectOption[]>(() =>
    [...this.pipelineStages()]
      .sort((a, b) => a.display_order - b.display_order)
      .map((s) => ({ value: s.key, label: s.name })),
  );

  /** Guardrail against the SMTP-modal bug — computed(() => form.valid)
   *  wouldn't re-evaluate on user input because `form.valid` isn't a
   *  signal. `toSignal(statusChanges)` bridges it. */
  protected readonly form: FormGroup<FormShape> = this.fb.group<FormShape>({
    contact_full_name: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(255)],
    }),
    contact_phone: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(32)],
    }),
    contact_email: this.fb.control<string>('', {
      nonNullable: true,
      validators: [commonValidators.email, Validators.maxLength(255)],
    }),
    source: this.fb.control<LeadSource>('manual', { nonNullable: true }),
    pipeline_stage: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(64)],
    }),
    assigned_to_id: this.fb.control<string>('', { nonNullable: true }),
    // Remarks used to be `Validators.required`, which meant the
    // Update Profile button stayed disabled whenever the rep edited
    // anything OTHER than Owner (Owner-change auto-fills a
    // "Reassigned from A to B." remark, satisfying the validator by
    // side-effect). Making it optional lets a rep edit contact /
    // stage / source / status / follow-up without also having to
    // type an explanation. Length cap stays (matches the backend).
    remarks: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(REMARKS_MAX)],
    }),
    next_follow_up_at: this.fb.control<string>('', {
      nonNullable: true,
      validators: [this._followUpAtBoundsValidator.bind(this)],
    }),
    next_follow_up_type: this.fb.control<FollowUpType>('call', { nonNullable: true }),
    lost_reason: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(32)],
    }),
    lost_reason_other: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(255)],
    }),
  });

  private readonly formStatus = toSignal(this.form.statusChanges, {
    initialValue: this.form.status,
  });
  protected readonly isFormValid = computed(() => this.formStatus() === 'VALID');
  // Bridge `form.dirty` into a signal — plain `form.dirty` isn't
  // reactive on its own, so gate the button off the same
  // `valueChanges` stream that flips the dirty flag.
  private readonly formValue = toSignal(this.form.valueChanges, {
    initialValue: this.form.getRawValue(),
  });
  protected readonly isFormDirty = computed<boolean>(() => {
    // Touch the value signal so this computed re-runs on any input.
    // The form's own `dirty` flag is what we're actually reading —
    // `formValue()` is discarded, it just wakes the tracker.
    void this.formValue();
    return this.form.dirty;
  });
  protected readonly submitDisabled = computed(
    () =>
      this.submitting() ||
      !this.isFormValid() ||
      !this.isFormDirty() ||
      this.stageDriftedTo() !== null,
  );

  /** Captured on open. Sent as ``if_current_stage`` so the backend
   *  rejects submissions where a colleague moved the lead in the
   *  meantime — 409 becomes the drift banner. */
  private originalStage = '';
  /** The lead's owner-id at modal-open time. Compared against
   *  `form.controls.assigned_to_id` in the payload builder to decide
   *  whether to ship `set_assigned_to=true`. `''` = Unassigned. */
  private originalOwner = '';
  /** The exact "Reassigned from A to B." sentence we last auto-prepended
   *  to the Remarks textarea. Stored so we can rewrite / remove it when
   *  the owner selection changes again — without ever clobbering text
   *  the rep typed themselves. `''` = no auto-remark active. */
  private autoRemarksSeed = '';

  /** True when the currently-selected pipeline_stage is a Lost stage —
   *  the reason picker + free-text row become required. Read from the
   *  form so the template can toggle visibility with a single `@if`. */
  protected readonly stageIsLost = computed<boolean>(() => {
    const key = this.formStatus() ? this.form.controls.pipeline_stage.value : '';
    const stage = this.pipelineStages().find((s) => s.key === key);
    return !!stage?.is_lost;
  });

  protected readonly stageIsWon = computed<boolean>(() => {
    const key = this.formStatus() ? this.form.controls.pipeline_stage.value : '';
    const stage = this.pipelineStages().find((s) => s.key === key);
    return !!stage?.is_won;
  });

  constructor() {
    // Preload the form from the lead + contact once inputs settle.
    effect(() => {
      const l = this.lead();
      const c = this.contact();
      this.originalStage = l.pipeline_stage;
      this.form.reset({
        contact_full_name: c?.full_name ?? '',
        contact_phone: c?.phone ?? '',
        contact_email: c?.email ?? '',
        source: l.source,
        pipeline_stage: l.pipeline_stage,
        assigned_to_id: l.assigned_to_id ?? '',
        remarks: '',
        next_follow_up_at: this._defaultFollowUpAt(),
        next_follow_up_type: 'call',
        lost_reason: l.lost_reason ?? '',
        lost_reason_other: l.lost_reason_other ?? '',
      });
      // Remember the original owner so auto-remarks + payload builder
      // can tell when the rep actually touched the dropdown.
      this.originalOwner = l.assigned_to_id ?? '';
      this.autoRemarksSeed = '';
      // Clear per-submit error state whenever the modal re-opens with
      // a different lead.
      this.stageDriftedTo.set(null);
      this.sharedContactCount.set(null);
      this.errorBanner.set(null);
    });

    // Toggle lost-reason validators when the stage moves in/out of Lost.
    effect(() => {
      const isLost = this.stageIsLost();
      const reason = this.form.controls.lost_reason;
      const other = this.form.controls.lost_reason_other;
      if (isLost) {
        reason.setValidators([Validators.required, Validators.maxLength(32)]);
      } else {
        reason.setValidators([Validators.maxLength(32)]);
      }
      reason.updateValueAndValidity({ emitEvent: false });
      const needsOther = isLost && reason.value === 'other';
      if (needsOther) {
        other.setValidators([Validators.required, Validators.maxLength(255)]);
      } else {
        other.setValidators([Validators.maxLength(255)]);
      }
      other.updateValueAndValidity({ emitEvent: false });
    });

    // Load the org's user directory for the Owner dropdown + the
    // auto-remarks name lookup. One request per session (service caches).
    this.usersDir
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (users) => this.orgUsers.set(users),
        error: () => this.orgUsers.set([]),
      });
  }

  /** Owner-dropdown change handler. Prepends "Reassigned from A to B."
   *  to the Remarks textarea so every reassignment lands a searchable
   *  note on the timeline — the rep can add more context after it or
   *  wipe the whole thing before submit. Idempotent: if the effect
   *  fires again for a later owner pick, we rewrite the previously
   *  auto-inserted sentence in place instead of stacking multiple
   *  copies on top of each other. */
  protected onOwnerChange(newId: string): void {
    // `emitEvent: true` (default) on the setValue calls below is
    // deliberate — the modal's submit button reads `formStatus()`
    // (bridged from `form.statusChanges`), so auto-filling the
    // previously-empty required Remarks field MUST emit the event or
    // the button stays disabled even though the form is now valid.
    this.form.controls.assigned_to_id.setValue(newId);
    const current = this.form.controls.remarks.value;
    // Strip the previous auto-insertion (if any and still at the top
    // untouched) so we can rewrite it against the freshly-picked owner.
    let base = current;
    if (this.autoRemarksSeed && current.startsWith(this.autoRemarksSeed)) {
      base = current.slice(this.autoRemarksSeed.length).trimStart();
    }
    // No reassignment if the owner just returned to its original value.
    if (newId === this.originalOwner) {
      this.autoRemarksSeed = '';
      this.form.controls.remarks.setValue(base);
      return;
    }
    const fromLabel = this.ownerLabel(this.originalOwner || null);
    const toLabel = this.ownerLabel(newId || null);
    const seed = `Reassigned from ${fromLabel} to ${toLabel}.`;
    const joined = base.length > 0 ? `${seed} ${base}` : seed;
    this.autoRemarksSeed = seed + (base.length > 0 ? ' ' : '');
    this.form.controls.remarks.setValue(joined);
    this.form.controls.remarks.markAsDirty();
    this.form.controls.remarks.markAsTouched();
  }

  cancel(): void {
    if (this.submitting()) return;
    this.cancelled.emit();
  }

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) this.cancel();
  }

  submit(): void {
    if (this.submitting() || !this.isFormValid()) return;
    if (this.stageDriftedTo() !== null) return;
    this.errorBanner.set(null);
    this.submitting.set(true);

    const raw = this.form.getRawValue();
    const l = this.lead();
    const payload: LogUpdateRequest = {
      if_current_stage: this.originalStage,
      remarks: raw.remarks.trim(),
    };

    // Only ship contact_basics when the rep actually changed one of
    // the three fields — sending unchanged values would still trigger
    // the shared-contact guard on a contact linked to multiple leads.
    const c = this.contact();
    const patched: Record<string, string> = {};
    if (raw.contact_full_name.trim() !== (c?.full_name ?? '')) {
      patched['full_name'] = raw.contact_full_name.trim();
    }
    if (raw.contact_phone.trim() !== (c?.phone ?? '')) {
      patched['phone'] = raw.contact_phone.trim();
    }
    if (raw.contact_email.trim() !== (c?.email ?? '')) {
      patched['email'] = raw.contact_email.trim();
    }
    if (Object.keys(patched).length > 0) {
      payload.contact_basics = patched;
    }

    if (raw.pipeline_stage !== l.pipeline_stage) {
      payload.pipeline_stage = raw.pipeline_stage;
    }
    if (raw.source !== l.source) {
      payload.source = raw.source;
    }
    // Owner change — sentinel + null-safe id. Backend requires
    // `set_assigned_to=true` to distinguish an intentional
    // "clear owner" (`assigned_to_id=null`) from "field omitted".
    const currentOwnerFormValue = raw.assigned_to_id ?? '';
    if (currentOwnerFormValue !== this.originalOwner) {
      payload.set_assigned_to = true;
      payload.assigned_to_id = currentOwnerFormValue === '' ? null : currentOwnerFormValue;
    }
    if (raw.next_follow_up_at) {
      // <input type="datetime-local"> gives us a local wall-clock time
      // with NO offset. Round-trip through Date() to convert to UTC ISO
      // for the server (which stores every timestamp as UTC).
      payload.next_follow_up = {
        due_at: new Date(raw.next_follow_up_at).toISOString(),
        followup_type: raw.next_follow_up_type,
      };
    }
    if (this.stageIsLost()) {
      payload.lost_reason = raw.lost_reason || null;
      payload.lost_reason_other = raw.lost_reason_other || null;
    }

    this.api
      .logUpdate(l.id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.submitting.set(false);
          this.saved.emit({
            lead: resp.lead,
            next_follow_up_task_id: resp.next_follow_up_task_id,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          if (err.status === 409) {
            const drifted = (err.error?.detail?.current_stage as string | undefined) ?? '';
            this.stageDriftedTo.set(drifted);
            return;
          }
          if (
            err.status === 422 &&
            typeof err.error?.detail === 'object' &&
            err.error.detail?.error === 'contact_shared'
          ) {
            const count = (err.error.detail.lead_count as number | undefined) ?? 2;
            this.sharedContactCount.set(count);
            this.form.controls.contact_full_name.disable({ emitEvent: false });
            this.form.controls.contact_phone.disable({ emitEvent: false });
            this.form.controls.contact_email.disable({ emitEvent: false });
            this.errorBanner.set(
              `This customer is on ${count} leads. Contact edits must be made from the contacts page — try again with only the other fields.`,
            );
            return;
          }
          this.errorBanner.set(extractApiError(err) ?? 'Could not save. Please try again.');
        },
      });
  }

  /** Validator: bound `next_follow_up_at` to the same window the
   *  backend enforces (`now - 1y ≤ v ≤ now + 5y`). Empty passes — the
   *  form-level required is toggled by the caller, not by this validator.
   *
   *  Typed as `AbstractControl` (not `FormControl<string>`) because
   *  `ValidatorFn` is contravariant in its input — Angular's stricter
   *  compile-time check (`ng serve`) rejects the narrower signature. */
  private _followUpAtBoundsValidator(
    control: AbstractControl,
  ): { followUpOutOfRange: string } | null {
    const raw = ((control.value as string | null | undefined) ?? '').toString();
    if (!raw) return null;
    const due = new Date(raw);
    if (Number.isNaN(due.getTime())) {
      return { followUpOutOfRange: 'Enter a valid date & time.' };
    }
    const now = Date.now();
    const earliest = now - FOLLOWUP_LOOKBACK_DAYS * 86_400_000;
    const latest = now + FOLLOWUP_LOOKAHEAD_DAYS * 86_400_000;
    const t = due.getTime();
    if (t < earliest || t > latest) {
      return {
        followUpOutOfRange: `Choose a date within ${FOLLOWUP_LOOKBACK_DAYS} days back and ${Math.round(
          FOLLOWUP_LOOKAHEAD_DAYS / 365,
        )} years ahead.`,
      };
    }
    return null;
  }

  /** Tomorrow at 10:00 in the user's local TZ, formatted as the
   *  ``YYYY-MM-DDTHH:mm`` string ``<input type="datetime-local">``
   *  wants. Sir's screenshot showed 1950 as a placeholder default;
   *  ship a sane one instead. */
  private _defaultFollowUpAt(): string {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(10, 0, 0, 0);
    const pad = (n: number): string => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
      d.getHours(),
    )}:${pad(d.getMinutes())}`;
  }
}
