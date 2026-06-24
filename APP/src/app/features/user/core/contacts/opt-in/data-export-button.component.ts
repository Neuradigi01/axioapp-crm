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

/**
 * DPDP right-to-access export button on the contact-detail page
 * (whatsapp-platform-upgrade Step 23).
 *
 * Downloads a ZIP containing the contact's profile + consent log
 * + leads + per-conversation transcripts (CSV + PDF). Anyone with
 * ``contacts.read`` can request the export — DPDP §11(a) requires
 * the data fiduciary to make this available; the server audits
 * the download with the requester's user id.
 */
@Component({
  selector: 'app-contact-data-export-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
      [disabled]="busy()"
      (click)="download()"
      title="DPDP right-to-access: download all data we hold about this contact."
    >
      <lucide-icon name="download" class="h-3.5 w-3.5" />
      {{ busy() ? 'Preparing…' : 'Export contact data' }}
    </button>
    @if (error(); as err) {
      <p class="mt-1 text-[11px] text-rose-700">{{ err }}</p>
    }
  `,
})
export class ContactDataExportButtonComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  readonly contactId = input.required<string>();

  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);

  protected download(): void {
    const id = this.contactId();
    if (!id) return;
    this.busy.set(true);
    this.error.set(null);
    this.http
      .get(
        `${environment.apiBaseUrl}/contacts/${id}/data-export`,
        { responseType: 'blob' },
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob: Blob) => {
          this.busy.set(false);
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `contact-${id}-data-export.zip`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not prepare data export.',
          );
        },
      });
  }
}
