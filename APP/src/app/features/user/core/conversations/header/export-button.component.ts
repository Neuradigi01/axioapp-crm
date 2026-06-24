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
    <div class="relative inline-block">
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-full border border-zinc-300 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
        (click)="toggle(); $event.stopPropagation()"
        [disabled]="busy()"
        aria-label="Export conversation"
      >
        <lucide-icon name="download" class="h-3 w-3" />
        Export
      </button>
      @if (open()) {
        <div
          class="absolute right-0 z-50 mt-1 w-32 rounded-md border border-zinc-200 bg-white py-1 text-xs shadow-lg"
          (click)="$event.stopPropagation()"
        >
          <button
            type="button"
            class="block w-full px-3 py-1.5 text-left text-zinc-700 hover:bg-zinc-50"
            (click)="download('csv')"
          >
            CSV
          </button>
          <button
            type="button"
            class="block w-full px-3 py-1.5 text-left text-zinc-700 hover:bg-zinc-50"
            (click)="download('pdf')"
          >
            PDF
          </button>
        </div>
      }
      @if (error(); as err) {
        <p class="absolute right-0 z-50 mt-1 w-64 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
          {{ err }}
        </p>
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

  protected toggle(): void {
    this.open.set(!this.open());
    this.error.set(null);
  }

  protected download(format: ExportFormat): void {
    const id = this.conversationId();
    if (!id) return;
    this.busy.set(true);
    this.error.set(null);
    this.http
      .get(
        `${environment.apiBaseUrl}/conversations/${id}/export.${format}`,
        { responseType: 'blob' },
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob: Blob) => {
          this.busy.set(false);
          this.open.set(false);
          this.triggerDownload(
            blob,
            `conversation-${id}.${format}`,
          );
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(
            extractApiError(err) ?? `Could not export ${format.toUpperCase()}.`,
          );
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
