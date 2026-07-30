import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { ContactImportListItem, ContactsApiService } from '../contacts-api.service';

/**
 * `/user/contacts/import/history` — forensic trail of every contact
 * import this org has run. Parity with the leads-import history page
 * at `/user/leads/import-history`.
 *
 * Server-side paginated (20 per page) + filtered by status. Rows expose:
 *   - Download errors / duplicates / warnings — one button per non-zero count
 *   - Open group — if the import created one
 *
 * Reached via the "View history" link on the upload page or directly.
 * No sidebar entry (sidebar is registry-driven per Rule 5).
 */

const PAGE_SIZE = 20;

type StatusFilter =
  | 'all'
  | 'uploaded'
  | 'dry_run'
  | 'processing'
  | 'committed'
  | 'failed'
  | 'cancelled';

@Component({
  selector: 'app-contact-import-history-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './import-history.page.html',
})
export class ContactImportHistoryPageComponent {
  private readonly api = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rows = signal<ContactImportListItem[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  protected readonly statusFilter = signal<StatusFilter>('all');
  protected readonly page = signal(1);
  protected readonly downloading = signal<string | null>(null);
  protected readonly downloadMsg = signal<string | null>(null);

  protected readonly pageSize = PAGE_SIZE;

  protected readonly statusOptions: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'uploaded', label: 'Uploaded' },
    { value: 'dry_run', label: 'Dry-run' },
    { value: 'processing', label: 'Processing' },
    { value: 'committed', label: 'Committed' },
    { value: 'failed', label: 'Failed' },
    { value: 'cancelled', label: 'Cancelled' },
  ];

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));

  protected readonly hasResults = computed(() => this.rows().length > 0);

  constructor() {
    effect(() => {
      const s = this.statusFilter();
      const p = this.page();
      void s;
      void p;
      this.fetch();
    });
  }

  private fetch(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const statusValue = this.statusFilter();
    this.api
      .listImports({
        status: statusValue === 'all' ? undefined : statusValue,
        page: this.page(),
        size: PAGE_SIZE,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.rows.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load import history.');
        },
      });
  }

  protected onStatusChange(event: Event): void {
    this.statusFilter.set((event.target as HTMLSelectElement).value as StatusFilter);
    this.page.set(1);
  }

  protected nextPage(): void {
    if (this.page() < this.totalPages()) this.page.update((p) => p + 1);
  }

  protected prevPage(): void {
    if (this.page() > 1) this.page.update((p) => p - 1);
  }

  // --- per-row download actions ------------------------------------

  protected downloadErrors(row: ContactImportListItem): void {
    this.runDownload(row.id, 'errors', () => this.api.downloadImportErrors(row.id));
  }

  protected downloadSkipped(row: ContactImportListItem): void {
    this.runDownload(row.id, 'skipped', () => this.api.downloadImportSkipped(row.id));
  }

  protected downloadWarnings(row: ContactImportListItem): void {
    this.runDownload(row.id, 'warnings', () => this.api.downloadImportWarnings(row.id));
  }

  private runDownload(
    importId: string,
    kind: 'errors' | 'skipped' | 'warnings',
    exec: () => import('rxjs').Observable<Blob>,
  ): void {
    if (this.downloading()) return;
    this.downloading.set(importId);
    this.downloadMsg.set(null);
    exec()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloading.set(null);
          this.triggerBlobDownload(blob, `contact-import-${importId}-${kind}.csv`);
        },
        error: (err: HttpErrorResponse) => {
          this.downloading.set(null);
          this.downloadMsg.set(extractApiError(err) ?? `Could not download the ${kind} CSV.`);
        },
      });
  }

  private triggerBlobDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // --- display helpers ----------------------------------------------

  protected statusLabel(status: string): string {
    switch (status) {
      case 'uploaded':
        return 'Uploaded';
      case 'dry_run':
        return 'Dry-run';
      case 'processing':
        return 'Processing';
      case 'committed':
        return 'Committed';
      case 'failed':
        return 'Failed';
      case 'cancelled':
        return 'Cancelled';
      default:
        return status;
    }
  }

  protected statusBadgeClass(status: string): string {
    switch (status) {
      case 'committed':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'failed':
        return 'bg-red-100 text-red-700 ring-red-200';
      case 'processing':
      case 'dry_run':
        return 'bg-blue-100 text-blue-700 ring-blue-200';
      case 'cancelled':
        return 'bg-red-50 text-red-500 ring-red-100';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  protected relativeTime(iso: string): string {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const seconds = Math.round((now - then) / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 30) return `${days}d ago`;
    const months = Math.round(days / 30);
    return `${months}mo ago`;
  }

  protected absoluteTime(iso: string): string {
    return new Date(iso).toLocaleString();
  }
}
