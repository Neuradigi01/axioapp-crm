import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { QrDownloadComponent } from './qr-download.component';
import { QuickLinkEditorComponent } from './quick-link-editor.component';
import { QuickLink, QuickLinkPage, QuickLinksService } from './quick-links.service';

type Mode = 'list' | 'edit';

/**
 * Step 26 — `/user/whatsapp/quick-links` page.
 *
 * Single-screen list with inline editor + QR preview. Operators
 * pick a row → the right pane shows the QR + download buttons +
 * stats; the +N counters live on the row chips so the page reads
 * "I've got 12 links, the billboard pulled 88 scans, 7 became
 * conversations" at a glance.
 */
@Component({
  selector: 'app-whatsapp-quick-links-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, QrDownloadComponent, QuickLinkEditorComponent],
  template: `
    <div class="space-y-4 p-4">
      <header class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 class="text-xl font-semibold text-default">Quick contact links</h1>
          <p class="text-xs text-muted">
            Print on billboards, receipts, packaging. Each scan attributes the resulting
            conversation to the link.
          </p>
        </div>
        @if (mode() === 'list') {
          <button
            type="button"
            (click)="openCreate()"
            class="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:brightness-95"
          >
            <lucide-icon name="plus" class="h-3.5 w-3.5" />
            New link
          </button>
        } @else {
          <button
            type="button"
            (click)="backToList()"
            class="inline-flex items-center gap-1.5 rounded-md border border-subtle bg-surface px-3 py-1.5 text-xs text-default hover:bg-surface-2"
          >
            <lucide-icon name="arrow-left" class="h-3.5 w-3.5" />
            Back
          </button>
        }
      </header>

      @if (error(); as err) {
        <p class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {{ err }}
        </p>
      }
      @if (toast(); as msg) {
        <p class="rounded-md border border-subtle bg-surface-2 px-3 py-2 text-xs text-default">
          {{ msg }}
        </p>
      }

      @switch (mode()) {
        @case ('list') {
          <div class="overflow-hidden rounded-md border border-subtle bg-surface">
            <table class="w-full text-xs">
              <thead class="bg-surface-2 text-muted">
                <tr>
                  <th class="px-3 py-2 text-left font-medium">Label</th>
                  <th class="px-3 py-2 text-left font-medium">Slug</th>
                  <th class="px-3 py-2 text-left font-medium">Phone</th>
                  <th class="px-3 py-2 text-right font-medium">Clicks</th>
                  <th class="px-3 py-2 text-right font-medium">Scans</th>
                  <th class="px-3 py-2 text-right font-medium">Converted</th>
                  <th class="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-subtle">
                @for (row of page().items; track row.id) {
                  <tr>
                    <td class="px-3 py-2 font-medium text-default">
                      {{ row.label }}
                    </td>
                    <td class="px-3 py-2 font-mono text-[11px] text-muted">
                      {{ row.code }}
                    </td>
                    <td class="px-3 py-2 text-default">+{{ row.phone_number }}</td>
                    <td class="px-3 py-2 text-right text-default">{{ row.click_count }}</td>
                    <td class="px-3 py-2 text-right text-default">{{ row.scan_count }}</td>
                    <td class="px-3 py-2 text-right text-emerald-700">
                      {{ row.attributed_conversation_count }}
                    </td>
                    <td class="px-3 py-2 text-right">
                      <div class="inline-flex items-center gap-1">
                        <button
                          type="button"
                          (click)="onEdit(row)"
                          class="rounded border border-subtle bg-surface px-2 py-1 text-[11px] text-default hover:bg-surface-2"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          (click)="onDelete(row)"
                          class="rounded border border-red-500/30 bg-surface px-2 py-1 text-[11px] text-red-400 hover:bg-red-500/10"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="7" class="px-3 py-6 text-center text-muted">
                      No links yet. Click <em>New link</em> to create the first one.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        @case ('edit') {
          <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <app-quick-link-editor
              [editing]="editing()"
              (saved)="onSaved($event)"
              (cancel)="backToList()"
            />
            <app-qr-download [link]="editing()" />
          </div>
        }
      }
    </div>
  `,
})
export class WhatsAppQuickLinksPageComponent {
  private readonly api = inject(QuickLinksService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly page = signal<QuickLinkPage>({
    items: [],
    total: 0,
    page: 1,
    size: 50,
  });
  protected readonly mode = signal<Mode>('list');
  protected readonly editing = signal<QuickLink | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  constructor() {
    this.load();
  }

  protected openCreate(): void {
    this.editing.set(null);
    this.mode.set('edit');
  }

  protected onEdit(row: QuickLink): void {
    this.editing.set(row);
    this.mode.set('edit');
  }

  protected backToList(): void {
    this.editing.set(null);
    this.mode.set('list');
    this.error.set(null);
    this.toast.set(null);
  }

  protected onSaved(row: QuickLink): void {
    this.toast.set(`Saved "${row.label}".`);
    this.editing.set(row);
    this.load();
  }

  protected onDelete(row: QuickLink): void {
    if (!confirm(`Delete link "${row.label}"? The public URL will 404.`)) {
      return;
    }
    this.api
      .remove(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.toast.set(`Deleted "${row.label}".`);
          this.load();
        },
        error: (err: HttpErrorResponse) => this.error.set(extractApiError(err) ?? 'Delete failed.'),
      });
  }

  private load(): void {
    this.error.set(null);
    this.api
      .list(1, 100)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => this.page.set(p),
        error: (err: HttpErrorResponse) =>
          this.error.set(extractApiError(err) ?? 'Could not load links.'),
      });
  }
}
