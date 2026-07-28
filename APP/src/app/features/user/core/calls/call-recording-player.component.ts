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
      <audio controls preload="metadata" [src]="src" class="h-8 max-w-xs">
        Your browser doesn't support inline audio playback.
      </audio>
    }
  `,
})
export class CallRecordingPlayerComponent implements OnDestroy {
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true })
  set callId(value: string) {
    this._callId = value;
    this.load();
  }
  private _callId = '';

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly blobUrl = signal<string | null>(null);

  private load(): void {
    // Revoke any prior blob URL (e.g. when the input changes).
    const prior = this.blobUrl();
    if (prior) URL.revokeObjectURL(prior);
    this.blobUrl.set(null);
    this.loading.set(true);
    this.error.set(null);

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
