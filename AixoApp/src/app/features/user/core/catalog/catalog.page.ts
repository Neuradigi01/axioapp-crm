import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { InrPipe } from '../shared/pipes/inr.pipe';
import { CatalogApiService, CatalogItem } from './catalog-api.service';
import { AddItemModalComponent } from './add-item-modal.component';
import { ViewItemModalComponent } from './view-item-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { deriveApiOrigin } from '@core/services/url.util';

/**
 * Catalog page â€” bare-minimum product table matching the reference
 * Vercel layout's structural shape (header + KPI strip + search +
 * grid). The Phase 4 furniture pack will replace this with the
 * richer inventory page (stock + locations + alerts).
 */
@Component({
  selector: 'app-catalog-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    InrPipe,
    AddItemModalComponent,
    ViewItemModalComponent,
  ],
  templateUrl: './catalog.page.html',
})
export class CatalogPageComponent {
  private readonly api = inject(CatalogApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly items = signal<CatalogItem[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly categoryControl = new FormControl('', { nonNullable: true });

  private readonly q = toSignal(
    this.searchControl.valueChanges.pipe(debounceTime(200), distinctUntilChanged()),
    { initialValue: '' },
  );
  private readonly categoryFilter = toSignal(
    this.categoryControl.valueChanges.pipe(distinctUntilChanged()),
    { initialValue: '' },
  );

  /** Modal state: null = closed, undefined = create, CatalogItem = edit. */
  readonly modalState = signal<CatalogItem | null | undefined>(null);
  readonly modalOpen = computed(() => this.modalState() !== null);
  readonly editingItem = computed<CatalogItem | null>(() => {
    const v = this.modalState();
    return v === undefined ? null : (v ?? null);
  });

  /** View modal: read-only details, opens on card click. */
  readonly viewingItem = signal<CatalogItem | null>(null);

  /** Category options derived from the loaded list. */
  readonly categoryOptions = computed(() => {
    const set = new Set<string>();
    for (const i of this.items()) {
      if (i.category) set.add(i.category);
    }
    return [...set].sort();
  });

  // --- KPI cards ---

  readonly totalProducts = computed(() => this.total());
  readonly activeProducts = computed(() => this.items().filter((i) => i.is_active).length);
  readonly inactiveProducts = computed(() => this.items().filter((i) => !i.is_active).length);
  readonly distinctCategories = computed(() => this.categoryOptions().length);

  constructor() {
    this.reload();

    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
    this.categoryControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        q: this.q() || undefined,
        category: this.categoryFilter() || undefined,
        size: 200,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load catalog.');
        },
      });
  }

  protected openCreate(): void {
    this.modalState.set(undefined);
  }

  protected openEdit(item: CatalogItem): void {
    this.modalState.set(item);
  }

  protected closeModal(): void {
    this.modalState.set(null);
  }

  protected openView(item: CatalogItem): void {
    this.viewingItem.set(item);
  }

  protected closeView(): void {
    this.viewingItem.set(null);
  }

  /** "Edit" pressed from inside the view modal — hand off to the edit modal. */
  protected onEditFromView(item: CatalogItem): void {
    this.viewingItem.set(null);
    this.modalState.set(item);
  }

  protected onSaved(_item: CatalogItem): void {
    this.modalState.set(null);
    this.reload();
  }

  protected onDelete(item: CatalogItem): void {
    const ok = window.confirm(`Delete "${item.name}" (${item.sku})? This cannot be undone.`);
    if (!ok) return;
    const before = this.items();
    this.items.update((rows) => rows.filter((i) => i.id !== item.id));
    this.total.update((n) => n - 1);
    this.api
      .delete(item.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (err: HttpErrorResponse) => {
          this.items.set(before);
          this.total.set(before.length);
          this.loadError.set(extractApiError(err) ?? 'Could not delete item.');
        },
      });
  }

  /** Absolute URL for the backend-served `/files/...` image path. */
  private readonly apiOrigin = deriveApiOrigin();
  protected imageHref(item: CatalogItem): string | null {
    return item.image_url ? `${this.apiOrigin}${item.image_url}` : null;
  }

  /** Pick an emoji based on the category for the card icon. */
  protected emojiFor(category: string | null): string {
    if (!category) return 'ðŸ“¦';
    const c = category.toLowerCase();
    if (c.includes('sofa') || c.includes('couch')) return 'ðŸ›‹ï¸';
    if (c.includes('bed')) return 'ðŸ›ï¸';
    if (c.includes('chair')) return 'ðŸª‘';
    if (c.includes('table')) return 'ðŸªŸ';
    if (c.includes('dining')) return 'ðŸ½ï¸';
    if (c.includes('storage') || c.includes('shelf') || c.includes('cabinet')) return 'ðŸ—„ï¸';
    if (c.includes('light') || c.includes('lamp')) return 'ðŸ’¡';
    return 'ðŸ“¦';
  }
}
