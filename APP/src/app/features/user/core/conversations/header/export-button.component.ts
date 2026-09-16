import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

type ExportFormat = 'csv' | 'pdf';

/**
 * Conversation header export button (whatsapp-platform-upgrade Step 23).
 *
 * Downloads the transcript as CSV or PDF — both surfaces exclude
 * Step 13 internal notes. Read-gate `conversations.read` is
 * enforced server-side; the button is visible to anyone who can
 * read the conversation.
 */
@Component({
  selector: 'app-conversation-export-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    <div class="inline-block">
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-full border border-subtle bg-surface px-2.5 py-1 text-xs font-medium text-default hover:bg-surface-2"
        (click)="toggle(); $event.stopPropagation()"
        [disabled]="busy()"
        aria-label="Export conversation"
      >
        <lucide-icon name="download" class="h-3 w-3" />
        Export
      </button>

      @if (open()) {
        <!-- Fixed-position modal — matches the Block Number action so
             the picker is never clipped by the details-rail's
             overflow-y:auto ancestor. Backdrop click closes; inner
             card stops propagation. -->
        <div
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          (click)="close()"
        >
          <div
            class="w-full max-w-md rounded-lg border-subtle bg-surface shadow-xl ring-1"
            (click)="$event.stopPropagation()"
            role="dialog"
            aria-modal="true"
            aria-labelledby="export-conversation-title"
          >
            <header class="border-b border-subtle px-4 py-3 md:px-6 md:py-4">
              <h2 id="export-conversation-title" class="text-base font-semibold text-default">
                Export conversation
              </h2>
              <p class="mt-1 text-[14px] text-muted">
                Download the full transcript as CSV (spreadsheet) or PDF (printable). Internal notes
                are excluded from both formats.
              </p>
            </header>

            <div class="space-y-3 px-4 py-5 text-sm md:px-6">
              <button
                type="button"
                [disabled]="busy()"
                (click)="download('csv')"
                class="flex w-full items-center justify-between gap-3 rounded-lg border border-subtle bg-surface px-4 py-3 text-left transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span class="min-w-0 flex-1">
                  <span class="block text-sm font-semibold text-default">CSV</span>
                  <span class="mt-0.5 block text-xs text-muted">
                    One row per message — opens in Excel or Sheets.
                  </span>
                </span>
                @if (busy() && pendingFormat() === 'csv') {
                  <lucide-icon name="loader-2" class="h-4 w-4 shrink-0 animate-spin text-muted" />
                } @else {
                  <lucide-icon name="download" class="h-4 w-4 shrink-0 text-muted" />
                }
              </button>

              <button
                type="button"
                [disabled]="busy()"
                (click)="download('pdf')"
                class="flex w-full items-center justify-between gap-3 rounded-lg border border-subtle bg-surface px-4 py-3 text-left transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span class="min-w-0 flex-1">
                  <span class="block text-sm font-semibold text-default">PDF</span>
                  <span class="mt-0.5 block text-xs text-muted">
                    Formatted transcript for printing or sharing.
                  </span>
                </span>
                @if (busy() && pendingFormat() === 'pdf') {
                  <lucide-icon name="loader-2" class="h-4 w-4 shrink-0 animate-spin text-muted" />
                } @else {
                  <lucide-icon name="download" class="h-4 w-4 shrink-0 text-muted" />
                }
              </button>

              @if (error(); as err) {
                <div
                  class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400"
                >
                  {{ err }}
                </div>
              }
            </div>

            <footer
              class="flex items-center justify-end gap-2 border-t border-subtle px-4 py-3 md:px-6"
            >
              <button
                type="button"
                (click)="close()"
                [disabled]="busy()"
                class="rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm font-medium text-default hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
            </footer>
          </div>
        </div>
      }
    </div>
  `,
})
export class ConversationExportButtonComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  readonly conversationId = input.required<string>();

  protected readonly open = signal<boolean>(false);
  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  /** Which format is currently downloading — drives the per-row
   *  spinner on the two option cards so the operator can tell which
   *  button they clicked while the blob request is in flight. */
  protected readonly pendingFormat = signal<ExportFormat | null>(null);

  protected toggle(): void {
    this.open.set(!this.open());
    this.error.set(null);
  }

  protected close(): void {
    if (this.busy()) return;
    this.open.set(false);
    this.error.set(null);
  }

  protected download(format: ExportFormat): void {
    const id = this.conversationId();
    if (!id) return;
    this.busy.set(true);
    this.pendingFormat.set(format);
    this.error.set(null);
    this.http
      .get(`${environment.apiBaseUrl}/conversations/${id}/export.${format}`, {
        responseType: 'blob',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob: Blob) => {
          this.busy.set(false);
          this.pendingFormat.set(null);
          this.open.set(false);
          this.triggerDownload(blob, `conversation-${id}.${format}`);
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.pendingFormat.set(null);
          this.error.set(extractApiError(err) ?? `Could not export ${format.toUpperCase()}.`);
        },
      });
  }

  private triggerDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }
}
