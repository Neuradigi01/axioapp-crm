import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Input,
  OnDestroy,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { CallsApiService } from './calls-api.service';

/**
 * Inline `<audio>` player for a call recording.
 *
 * Fetches the recording via `HttpClient` so the JWT interceptor sends
 * the Authorization header — `<audio src>` alone can't send bearer
 * tokens. Bytes are wrapped in a blob URL that the browser plays back
 * natively. The blob URL is released on component destroy so we don't
 * leak memory when the parent list re-renders.
 *
 * Fetch is **gated behind the Play button** — mounting the component
 * for every row of the Logs table would otherwise dispatch one
 * blob download per row on tab open (200 rows → 200 concurrent
 * downloads even for calls the user never plays). The blob is only
 * fetched when the operator explicitly asks for it.
 */
@Component({
  selector: 'app-call-recording-player',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    @if (loading()) {
      <div class="inline-flex items-center gap-1 text-[11px] text-muted">
        <lucide-icon
          name="loader-2"
          size="12"
          class="animate-spin"
          aria-hidden="true"
        ></lucide-icon>
        Loading…
      </div>
    } @else if (error()) {
      <span class="text-[11px] text-red-500">{{ error() }}</span>
    } @else if (blobUrl(); as src) {
      <audio controls autoplay preload="metadata" [src]="src" class="h-8 max-w-xs">
        Your browser doesn't support inline audio playback.
      </audio>
    } @else {
      <button
        type="button"
        (click)="load()"
        class="inline-flex items-center gap-1 rounded-md border border-subtle bg-surface px-2 py-1 text-[11px] font-medium text-default hover:bg-surface-2"
        title="Load and play recording"
      >
        <lucide-icon name="play" size="12" aria-hidden="true"></lucide-icon>
        Play
      </button>
    }
  `,
})
export class CallRecordingPlayerComponent implements OnDestroy {
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true })
  set callId(value: string) {
    // If the parent swaps the id (row edit, list refresh), discard the
    // prior blob so a later `load()` targets the new recording — but
    // do NOT auto-fetch. See class docstring.
    if (this._callId !== value) {
      const prior = this.blobUrl();
      if (prior) URL.revokeObjectURL(prior);
      this.blobUrl.set(null);
      this.error.set(null);
    }
    this._callId = value;
  }
  private _callId = '';

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly blobUrl = signal<string | null>(null);

  protected load(): void {
    // Guard against double-clicks or repeated Play presses while the
    // fetch is already in flight or the blob already exists.
    if (this.loading() || this.blobUrl() !== null) return;
    this.error.set(null);
    this.loading.set(true);

    this.api
      .fetchRecording(this._callId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.blobUrl.set(URL.createObjectURL(blob));
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(err.status === 404 ? 'No recording' : 'Playback error');
          this.loading.set(false);
        },
      });
  }

  ngOnDestroy(): void {
    const url = this.blobUrl();
    if (url) URL.revokeObjectURL(url);
  }
}
