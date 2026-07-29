import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { extractApiError } from '@core/services/api-error.util';

import { Call, CallTranscript, CallsApiService } from '../calls-api.service';

/**
 * Transcripts tab — left rail of calls (newest first), right pane shows
 * the transcript for the selected call. Admin can edit + save the
 * transcript (PUT replaces the single row per call).
 *
 * Calls without an existing transcript yield a 404 on GET; we treat
 * that as "no transcript yet" rather than an error, and let the user
 * type one and PUT.
 */
@Component({
  selector: 'app-call-transcripts-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './transcripts.component.html',
})
export class CallTranscriptsTabComponent {
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly calls = signal<Call[]>([]);
  protected readonly callsLoading = signal(false);
  protected readonly listError = signal<string | null>(null);

  protected readonly selectedId = signal<string | null>(null);
  protected readonly transcript = signal<CallTranscript | null>(null);
  protected readonly transcriptLoading = signal(false);
  protected readonly transcriptHas404 = signal(false);
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);

  protected readonly textControl = new FormControl('', { nonNullable: true });
  protected readonly langControl = new FormControl('en', { nonNullable: true });

  protected readonly selectedCall = computed<Call | null>(() => {
    const id = this.selectedId();
    return this.calls().find((c) => c.id === id) ?? null;
  });

  constructor() {
    this.reloadCalls();
  }

  protected pick(id: string): void {
    this.selectedId.set(id);
    this.loadTranscript(id);
  }

  protected save(): void {
    const id = this.selectedId();
    if (!id) return;
    if (!this.textControl.value.trim()) return;
    this.saving.set(true);
    this.saveError.set(null);
    this.api
      .upsertTranscript(id, {
        text: this.textControl.value,
        language: this.langControl.value || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (t) => {
          this.transcript.set(t);
          this.transcriptHas404.set(false);
          this.saving.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Could not save transcript.');
        },
      });
  }

  protected formatTimestamp(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  protected reloadCalls(): void {
    this.callsLoading.set(true);
    this.listError.set(null);
    this.api
      .listCalls({ size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.calls.set(resp.items);
          this.callsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.calls.set([]);
          this.callsLoading.set(false);
          this.listError.set(extractApiError(err) ?? 'Could not load calls.');
        },
      });
  }

  private loadTranscript(callId: string): void {
    this.transcriptLoading.set(true);
    this.transcriptHas404.set(false);
    this.transcript.set(null);
    this.textControl.setValue('');
    this.langControl.setValue('en');
    this.saveError.set(null);
    this.api
      .getTranscript(callId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (t) => {
          this.transcript.set(t);
          this.textControl.setValue(t.text);
          this.langControl.setValue(t.language ?? 'en');
          this.transcriptLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.transcriptLoading.set(false);
          if (err.status === 404) {
            this.transcriptHas404.set(true);
          } else {
            this.saveError.set(extractApiError(err) ?? 'Could not load transcript.');
          }
        },
      });
  }
}
