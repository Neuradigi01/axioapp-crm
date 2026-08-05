import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { MobileSelectComponent } from '../../shared/forms/mobile-select.component';
import {
  ImportsApiService,
  LeadImport,
  LeadImportStatus,
  SourcePlatform,
} from './imports-api.service';

/**
 * `/user/leads/import-history` — forensic trail of every import this
 * org has ever run.
 *
 * Server-side paginated (20 per page) + filtered by status +
 * source-platform. Per-row kebab exposes:
 *
 *   - Download source — original uploaded file
 *   - Download errors — error CSV (only if errors > 0)
 *   - Cancel          — only on `mapping_committed` / `processing`
 *
 * Status badge colour matrix follows the spec:
 *   gray  → awaiting_mapping, cancelled
 *   blue  → mapping_committed, processing
 *   green → completed
 *   red   → failed
 *
 * No sidebar entry (sidebar is registry-driven per Rule 5). Reached
 * via the "View history" link on the upload page, or directly.
 */

const PAGE_SIZE = 20;

type StatusFilter = 'all' | LeadImportStatus;
type PlatformFilter = 'all' | SourcePlatform;

interface KebabOpen {
  importId: string | null;
}

@Component({
  selector: 'app-import-history-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, MobileSelectComponent],
  templateUrl: './history-page.component.html',
})
export class HistoryPageComponent {
  private readonly api = inject(ImportsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rows = signal<LeadImport[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  protected readonly statusFilter = signal<StatusFilter>('all');
  protected readonly platformFilter = signal<PlatformFilter>('all');
  protected readonly page = signal(1);
  protected readonly downloading = signal<string | null>(null);
  protected readonly cancelling = signal<string | null>(null);

  protected readonly kebab = signal<KebabOpen>({ importId: null });

  protected readonly pageSize = PAGE_SIZE;

  protected readonly statusOptions: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'awaiting_mapping', label: 'Awaiting mapping' },
    { value: 'mapping_committed', label: 'Queued' },
    { value: 'processing', label: 'Processing' },
    { value: 'completed', label: 'Completed' },
    { value: 'failed', label: 'Failed' },
    { value: 'cancelled', label: 'Cancelled' },
  ];

  protected readonly platformOptions: { value: PlatformFilter; label: string }[] = [
    { value: 'all', label: 'All sources' },
    { value: 'zoho', label: 'Zoho' },
    { value: 'hubspot', label: 'HubSpot' },
    { value: 'salesforce', label: 'Salesforce' },
    { value: 'freshsales', label: 'Freshsales' },
    { value: 'generic_csv', label: 'Generic CSV' },
    { value: 'custom', label: 'Custom' },
  ];

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));

  protected readonly hasResults = computed(() => this.rows().length > 0);

  constructor() {
    // Refetch whenever filters or page change.
    effect(() => {
      const s = this.statusFilter();
      const p = this.platformFilter();
      const page = this.page();
      void s;
      void p;
      void page;
      this.fetch();
    });
  }

  private fetch(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        status:
          this.statusFilter() === 'all' ? undefined : (this.statusFilter() as LeadImportStatus),
        sourcePlatform:
          this.platformFilter() === 'all' ? undefined : (this.platformFilter() as SourcePlatform),
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

  // --- filter handlers ----------------------------------------------

  protected onStatusChange(event: Event): void {
    this.statusFilter.set((event.target as HTMLSelectElement).value as StatusFilter);
    this.page.set(1);
  }

  protected onPlatformChange(event: Event): void {
    this.platformFilter.set((event.target as HTMLSelectElement).value as PlatformFilter);
    this.page.set(1);
  }

  /** Value-only variants for `<crm-mobile-select>`. */
  protected onStatusValue(value: string): void {
    this.statusFilter.set(value as StatusFilter);
    this.page.set(1);
  }

  protected onPlatformValue(value: string): void {
    this.platformFilter.set(value as PlatformFilter);
    this.page.set(1);
  }

  protected nextPage(): void {
    if (this.page() < this.totalPages()) this.page.update((p) => p + 1);
  }

  protected prevPage(): void {
    if (this.page() > 1) this.page.update((p) => p - 1);
  }

  // --- kebab + actions ----------------------------------------------

  protected toggleKebab(importId: string): void {
    this.kebab.update((k) => (k.importId === importId ? { importId: null } : { importId }));
  }

  protected closeKebab(): void {
    this.kebab.set({ importId: null });
  }

  protected isKebabOpen(importId: string): boolean {
    return this.kebab().importId === importId;
  }

  protected canCancel(row: LeadImport): boolean {
    return (
      row.status === 'awaiting_mapping' ||
      row.status === 'mapping_committed' ||
      row.status === 'processing'
    );
  }

  protected hasErrors(row: LeadImport): boolean {
    return (row.counts?.errors ?? 0) > 0 && !!row.error_report_path;
  }

  protected downloadSource(row: LeadImport): void {
    this.closeKebab();
    this.downloading.set(row.id);
    this.api
      .downloadSource(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => this.triggerBlobDownload(blob, row.original_filename),
        error: () => this.loadError.set('Could not download source file.'),
        complete: () => this.downloading.set(null),
      });
  }

  protected downloadErrors(row: LeadImport): void {
    this.closeKebab();
    this.downloading.set(row.id);
    this.api
      .downloadErrors(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => this.triggerBlobDownload(blob, `import-${row.id}-errors.csv`),
        error: () => this.loadError.set('Could not download error report.'),
        complete: () => this.downloading.set(null),
      });
  }

  protected cancelImport(row: LeadImport): void {
    this.closeKebab();
    if (!confirm(`Cancel import "${row.name}"?`)) return;
    this.cancelling.set(row.id);
    this.api
      .cancel(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.cancelling.set(null);
          this.fetch();
        },
        error: (err: HttpErrorResponse) => {
          this.cancelling.set(null);
          this.loadError.set(extractApiError(err) ?? 'Could not cancel import.');
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
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // --- display helpers ----------------------------------------------

  protected statusLabel(status: LeadImportStatus): string {
    switch (status) {
      case 'awaiting_mapping':
        return 'Awaiting mapping';
      case 'mapping_committed':
        return 'Queued';
      case 'processing':
        return 'Processing';
      case 'completed':
        return 'Completed';
      case 'failed':
        return 'Failed';
      case 'cancelled':
        return 'Cancelled';
    }
  }

  protected statusBadgeClass(status: LeadImportStatus): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'failed':
        return 'bg-red-100 text-red-700 ring-red-200';
      case 'mapping_committed':
      case 'processing':
        return 'bg-blue-100 text-blue-700 ring-blue-200';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  protected platformLabel(value: string): string {
    const match = this.platformOptions.find((p) => p.value === value);
    return match?.label ?? value;
  }

  protected formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
    const d = new Date(iso);
    return d.toLocaleString();
  }
}
