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
  imports: [ReactiveFormsModule, LucideAngularModule],
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

  protected save(): void {
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
        next: (call) => this.afterCreate(call),
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
          // The Call row exists; recording failed. Surface the error
          // but still emit `saved` so the parent closes cleanly — the
          // rep can retry via the Edit Call flow later.
          this.submitError.set(
            extractApiError(err) ?? 'Call logged, but the recording upload failed.',
          );
          this.saved.emit(call);
        },
      });
  }

  protected close(): void {
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
