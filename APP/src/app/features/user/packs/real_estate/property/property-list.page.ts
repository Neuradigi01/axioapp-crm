import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';

import { assetUrl } from './asset-url.util';
import { PropertyApiService } from './property-api.service';
import { PropertyRowMenuComponent } from './property-row-menu.component';
import type { Property, PropertyStatus, PropertyTabKey } from './property.types';
import { PROPERTY_TABS } from './property.types';

/**
 * Owner-dashboard list page for the Property module.
 *
 * Layer 2 (Real Estate pack). Sidebar entry is auto-registered by the
 * backend `ModuleDescriptor` — this component only owns the page body.
 *
 * Scope for Step 6:
 *   - Tab bar (All / Draft / Published / Unpublished / Archived / Sold) with count badges.
 *   - Debounced search input, refetches on 300ms idle.
 *   - Server-side pagination (page / page_size).
 *   - Table columns: featured thumb, title + slug, status badge, price, city, updated_at.
 *
 * Out of scope until later steps:
 *   - Row click → detail/edit route (Step 7).
 *   - "New Property" CTA + create modal (Step 7).
 *   - Actions column (publish / archive / delete / copy URL) (Step 8).
 */
@Component({
  selector: 'app-property-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    LucideAngularModule,
    PropertyRowMenuComponent,
  ],
  templateUrl: './property-list.page.html',
})
export class PropertyListPageComponent {
  private readonly api = inject(PropertyApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);

  /** True while the "Share Listings" button is minting a token —
   *  disables the button and shows a "Copying…" label. */
  readonly listingsShareBusy = signal(false);

  protected readonly TABS = PROPERTY_TABS;

  protected readonly items = signal<Property[]>([]);
  protected readonly total = signal(0);
  protected readonly page = signal(1);
  protected readonly pageSize = signal(20);
  protected readonly statusCounts = signal<Partial<Record<PropertyStatus, number>>>({});
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly activeTab = signal<PropertyTabKey>('all');
  protected readonly searchControl = new FormControl('', { nonNullable: true });

  protected readonly totalPages = computed(() =>
    Math.max(1, Math.ceil(this.total() / this.pageSize())),
  );

  /** Total across every status — displayed on the "All" tab. */
  protected readonly allCount = computed(() =>
    Object.values(this.statusCounts()).reduce<number>((a, b) => a + (b ?? 0), 0),
  );

  constructor() {
    this.reload();

    this.searchControl.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
  }

  protected selectTab(tab: PropertyTabKey): void {
    if (this.activeTab() === tab) return;
    this.activeTab.set(tab);
    this.page.set(1);
    this.reload();
  }

  /** Mint the whole-listings share URL and copy it to the clipboard.
   *  Fernet-encrypted (same key scheme as per-property share) so it
   *  doesn't leak the org slug; rotating the property link key
   *  invalidates every outstanding listings URL at once. Falls back
   *  to a native prompt if the clipboard API isn't available. */
  protected shareListings(): void {
    if (this.listingsShareBusy()) return;
    this.listingsShareBusy.set(true);
    this.api
      .generateStorePublicUrl()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: async (resp) => {
          this.listingsShareBusy.set(false);
          const url = `${window.location.origin}/listings/${resp.token}`;
          try {
            await navigator.clipboard.writeText(url);
            this.toast.success('Listings URL copied to clipboard');
          } catch {
            window.prompt('Copy your public listings URL:', url);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.listingsShareBusy.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not generate listings URL.');
        },
      });
  }

  protected countForTab(tab: PropertyTabKey): number {
    if (tab === 'all') return this.allCount();
    return this.statusCounts()[tab] ?? 0;
  }

  protected reload(): void {
    const tab = this.activeTab();
    const statuses = tab === 'all' ? undefined : [tab as PropertyStatus];
    const search = this.searchControl.value.trim();

    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(
        {
          statuses,
          search: search || undefined,
          sort_by: 'created_at',
          sort_desc: true,
        },
        this.page(),
        this.pageSize(),
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.statusCounts.set(resp.status_counts);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Failed to load properties.');
          this.loading.set(false);
        },
      });
  }

  protected nextPage(): void {
    if (this.page() >= this.totalPages()) return;
    this.page.update((p) => p + 1);
    this.reload();
  }

  protected prevPage(): void {
    if (this.page() <= 1) return;
    this.page.update((p) => p - 1);
    this.reload();
  }

  protected onPageSizeChange(event: Event): void {
    const size = Number((event.target as HTMLSelectElement).value);
    if (!Number.isFinite(size) || size < 1) return;
    this.pageSize.set(size);
    this.page.set(1);
    this.reload();
  }

  protected openProperty(p: Property): void {
    this.router.navigate(['/user/properties', p.id, 'edit']);
  }

  protected imgSrc(p: Property): string {
    return assetUrl(p.featured_image_url);
  }

  /** Optimistic status update — the row menu emits this before the
   * server confirms. On error, the menu emits again with the previous
   * status; on success we still refetch to update tab counts. */
  protected applyOptimistic(event: { id: string; status: PropertyStatus }): void {
    this.items.update((all) =>
      all.map((p) => (p.id === event.id ? { ...p, status: event.status } : p)),
    );
  }

  /** Row disappeared (delete). Drop it and adjust the total; the next
   * refetch confirms tab counts. */
  protected removeRow(id: string): void {
    this.items.update((all) => all.filter((p) => p.id !== id));
    this.total.update((t) => Math.max(0, t - 1));
    // Refetch in background so tab counts reflect the deletion.
    this.reload();
  }

  protected statusBadgeClass(status: PropertyStatus): string {
    switch (status) {
      case 'published':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'unpublished':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'archived':
        return 'bg-surface-2 text-default border-subtle';
      case 'sold':
        return 'bg-blue-100 text-blue-700 ring-blue-200';
      case 'draft':
      default:
        return 'bg-surface-2 text-muted border-subtle';
    }
  }

  protected formatPrice(price: string | number | null, currency: string): string {
    if (price === null || price === undefined) return '—';
    const num = typeof price === 'string' ? Number(price) : price;
    if (!Number.isFinite(num)) return '—';
    try {
      return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: currency || 'INR',
        maximumFractionDigits: 0,
      }).format(num);
    } catch {
      return `${currency} ${num}`;
    }
  }
}
