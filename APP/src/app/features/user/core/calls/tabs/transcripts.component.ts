import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';

import { Call, CallTranscript, CallsApiService } from '../calls-api.service';
import { formatCallDuration, formatCallTime } from '../call-format.util';

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
  private readonly toast = inject(ToastService);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly injector = inject(Injector);

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

  /** Switching calls reloads the editor — ask first if the current
   *  transcript has unsaved edits. */
  protected async pick(id: string): Promise<void> {
    if (id === this.selectedId()) return;
    if (this.textControl.dirty || this.langControl.dirty) {
      const ok = await this.confirmDialog.ask({
        title: 'Discard unsaved transcript?',
        body: 'Your edits to this transcript have not been saved.',
        confirmLabel: 'Discard',
        danger: true,
      });
      if (!ok) return;
    }
    this.selectedId.set(id);
    this.loadTranscript(id);
    // Stacked layout (below `lg`): the editor sits under the list, so
    // bring it into view instead of leaving the click looking inert.
    afterNextRender(
      () => {
        if (window.matchMedia('(max-width: 1023px)').matches) {
          document
            .getElementById('call-transcript-pane')
            ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      },
      { injector: this.injector },
    );
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
          this.textControl.markAsPristine();
          this.langControl.markAsPristine();
          this.toast.success('Transcript saved');
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Could not save transcript.');
        },
      });
  }

  protected readonly formatTimestamp = formatCallTime;
  protected readonly formatDuration = formatCallDuration;

  /** Monotonic id for `reloadCalls()` — same last-write-wins guard as
   *  the sibling tabs. */
  private listSeq = 0;
  /** Monotonic id for the per-selection transcript fetch, so a rapid
   *  left-rail selection change can't paint the OLD call's transcript
   *  once its slower request finally resolves. */
  private transcriptSeq = 0;

  protected reloadCalls(): void {
    const seq = ++this.listSeq;
    this.callsLoading.set(true);
    this.listError.set(null);
    this.api
      .listCalls({ size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (seq !== this.listSeq) return;
          this.calls.set(resp.items);
          this.callsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.listSeq) return;
          this.calls.set([]);
          this.callsLoading.set(false);
          this.listError.set(extractApiError(err) ?? 'Could not load calls.');
        },
      });
  }

  private loadTranscript(callId: string): void {
    const seq = ++this.transcriptSeq;
    this.transcriptLoading.set(true);
    this.transcriptHas404.set(false);
    this.transcript.set(null);
    this.textControl.reset('');
    this.langControl.reset('en');
    this.saveError.set(null);
    this.api
      .getTranscript(callId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (t) => {
          if (seq !== this.transcriptSeq) return;
          this.transcript.set(t);
          this.textControl.setValue(t.text);
          this.langControl.setValue(t.language ?? 'en');
          this.transcriptLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.transcriptSeq) return;
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
