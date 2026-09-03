import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { extractApiError } from '@core/services/api-error.util';

import { commonValidators } from '../shared/validators';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
import { Call, CallOutcome, CallsApiService } from './calls-api.service';

/**
 * Modal to log a phone call. Reused by:
 *   - Logs tab (admin types from scratch).
 *   - Phone Book tab (click-to-call pre-fills `contact_id` + phone).
 *
 * `outcomes` is passed in by the parent (loaded once and shared) so we
 * don't refetch on every modal open.
 */
/** Per-file limit (matches backend `_MAX_RECORDING_BYTES`). */
const MAX_RECORDING_MB = 30;
const ALLOWED_RECORDING_EXTS = ['.mp3', '.m4a', '.ogg', '.wav'] as const;
/** Calls are always logged after the fact — accept up to 30 days back. */
const CALL_BACKFILL_DAYS = 30;
/** 24 hours max (matches DB CHECK constraint on duration_sec). */
const MAX_CALL_DURATION_SEC = 24 * 60 * 60;

const recordingUploadValidator = commonValidators.fileUpload({
  maxMb: MAX_RECORDING_MB,
  exts: ALLOWED_RECORDING_EXTS,
});

@Component({
  selector: 'app-log-call-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    MobileSelectComponent,
    MobileDateTimeComponent,
  ],
  templateUrl: './log-call-modal.component.html',
})
export class LogCallModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() set outcomes(list: CallOutcome[]) {
    this._outcomes = list;
    this.form.controls.outcome_id.setValidators([commonValidators.picklist(list.map((o) => o.id))]);
    this.form.controls.outcome_id.updateValueAndValidity({ emitEvent: false });
  }
  get outcomes(): CallOutcome[] {
    return this._outcomes;
  }
  private _outcomes: CallOutcome[] = [];
  /** Pre-fill the contact id (used by Phone Book's click-to-call). */
  @Input() set prefilledContactId(value: string | null) {
    if (value) {
      this.form.patchValue({ contact_id: value });
    }
  }
  /** Read-only label rendered if `prefilledContactId` is set. */
  @Input() prefilledContactName: string | null = null;

  @Output() readonly saved = new EventEmitter<Call>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  /** Audio file the user selected (drag-drop or click-to-pick). Uploaded
   *  after the Call row is created so we have a stable id to attach to. */
  protected readonly recordingFile = signal<File | null>(null);
  protected readonly recordingError = signal<string | null>(null);
  protected readonly dragActive = signal(false);
  protected readonly uploadingRecording = signal(false);

  /** Non-null once `POST /calls` succeeds. If the follow-up recording
   *  upload then fails, we keep the modal open — the call row already
   *  exists so the rep can pick a different file and retry the upload
   *  without re-creating the call. `close()` propagates this to the
   *  parent so the list still refreshes on manual dismiss. */
  protected readonly createdCall = signal<Call | null>(null);

  protected readonly recordingSizeLabel = computed(() => {
    const f = this.recordingFile();
    if (!f) return '';
    const mb = f.size / (1024 * 1024);
    return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB`;
  });

  protected readonly form = this.fb.group({
    contact_id: this.fb.control<string | null>(null),
    direction: this.fb.control<'in' | 'out'>('out', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    started_at: this.fb.control(this._nowIso(), {
      nonNullable: true,
      validators: [Validators.required, commonValidators.dateWithinPastDays(CALL_BACKFILL_DAYS)],
    }),
    duration_sec: this.fb.control(60, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(0), Validators.max(MAX_CALL_DURATION_SEC)],
    }),
    outcome_id: this.fb.control<string | null>(null),
    notes: this.fb.control<string | null>(null, [commonValidators.maxLength(4000)]),
  });

  /** Direction options for the mobile picker. */
  protected readonly directionOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'out', label: 'Outgoing' },
    { value: 'in', label: 'Incoming' },
  ];

  /** Outcome options list — includes the `null` "— Not set —"
   *  placeholder as an empty-string entry the mobile picker can handle
   *  (converted back to `null` in `onOutcomePicked`). */
  protected outcomeOptions(): ReadonlyArray<MobileSelectOption> {
    const opts: MobileSelectOption[] = [{ value: '', label: '— Not set —' }];
    for (const o of this._outcomes) opts.push({ value: o.id, label: o.label });
    return opts;
  }

  /** Value-only variants for `<crm-mobile-select>`. */
  protected onDirectionPicked(value: string): void {
    this.form.controls.direction.setValue(value as 'in' | 'out');
  }

  protected onOutcomePicked(value: string): void {
    this.form.controls.outcome_id.setValue(value || null);
  }

  /** Handler for `<crm-mobile-datetime>` — value is `YYYY-MM-DDTHH:mm`
   *  (same shape as the native input) so the form control's downstream
   *  `new Date(v.started_at).toISOString()` conversion still works. */
  protected onStartedAtPicked(value: string): void {
    this.form.controls.started_at.setValue(value);
  }

  /** ISO-local string for "30 days ago at 00:00" — the earliest slot
   *  the picker should offer as a `min` boundary. Matches the
   *  `dateWithinPastDays(CALL_BACKFILL_DAYS)` validator so the picker
   *  can't offer a value the validator will reject. */
  protected readonly minStartedAt = (() => {
    const d = new Date();
    d.setDate(d.getDate() - CALL_BACKFILL_DAYS);
    d.setHours(0, 0, 0, 0);
    const p = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(
      d.getMinutes(),
    )}`;
  })();

  /** ISO-local string for "now" — the latest slot the picker should
   *  offer. Recomputed lazily via a getter so it's fresh each open. */
  protected get maxStartedAt(): string {
    const d = new Date();
    const p = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(
      d.getMinutes(),
    )}`;
  }

  protected save(): void {
    // Post-create retry path: call already exists, only the recording
    // upload failed. Skip re-POST /calls and just retry the upload.
    const existing = this.createdCall();
    if (existing !== null) {
      this.afterCreate(existing);
      return;
    }
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    const v = this.form.getRawValue();
    this.api
      .createCall({
        contact_id: v.contact_id ?? null,
        direction: v.direction,
        started_at: new Date(v.started_at).toISOString(),
        duration_sec: v.duration_sec,
        outcome_id: v.outcome_id ?? null,
        notes: v.notes ?? null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (call) => {
          this.createdCall.set(call);
          this.afterCreate(call);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not log call.');
        },
      });
  }

  /** After the Call row lands, upload the recording (if any) then
   *  emit `saved`. The recording is a follow-up POST because the
   *  create endpoint takes JSON — we don't try to shove the audio
   *  through the same body. */
  private afterCreate(call: Call): void {
    const file = this.recordingFile();
    if (!file) {
      this.submitting.set(false);
      this.saved.emit(call);
      return;
    }
    this.uploadingRecording.set(true);
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .uploadRecording(call.id, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.uploadingRecording.set(false);
          this.submitting.set(false);
          this.saved.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.uploadingRecording.set(false);
          this.submitting.set(false);
          // The Call row exists; recording failed. Keep the modal open
          // so the rep can see the error, swap the file, and retry
          // the upload — there is no separate "edit call" flow to fall
          // back to. `close()` still emits `saved` so the parent's
          // list refreshes if the rep gives up and dismisses the modal.
          this.submitError.set(
            extractApiError(err) ?? 'Recording upload failed. Try a different file or dismiss.',
          );
        },
      });
  }

  protected close(): void {
    // If the call already landed but the recording upload didn't,
    // treat close as a "give up on the recording" — emit saved so the
    // parent list picks up the new call row instead of leaving it
    // stranded (invisible to the operator until a manual refresh).
    const existing = this.createdCall();
    if (existing !== null) {
      this.saved.emit(existing);
      return;
    }
    this.cancel.emit();
  }

  // --- Recording file picking -----------------------------------------

  protected onRecordingPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.acceptRecording(file);
    // Reset so re-selecting the same file still fires change.
    input.value = '';
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(true);
  }

  protected onDragLeave(): void {
    this.dragActive.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.acceptRecording(file);
  }

  protected clearRecording(): void {
    this.recordingFile.set(null);
    this.recordingError.set(null);
  }

  private acceptRecording(file: File): void {
    this.recordingError.set(null);
    const errors = recordingUploadValidator(new FormControl(file));
    if (errors?.['unsupportedFileType']) {
      this.recordingError.set(
        `Unsupported format. Allowed: ${ALLOWED_RECORDING_EXTS.join(', ')} (mp4/video is not accepted).`,
      );
      return;
    }
    if (errors?.['fileTooLarge']) {
      const mb = Math.round(file.size / (1024 * 1024));
      this.recordingError.set(
        `File is ${mb} MB — maximum is ${MAX_RECORDING_MB} MB. Try M4A instead of WAV.`,
      );
      return;
    }
    this.recordingFile.set(file);
  }

  private _nowIso(): string {
    // datetime-local input wants `YYYY-MM-DDTHH:mm` (no seconds, no TZ)
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
}
