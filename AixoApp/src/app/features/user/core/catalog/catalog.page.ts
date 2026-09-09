import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { RouterLink } from '@angular/router';

import { MobileSelectComponent } from '../shared/forms/mobile-select.component';
import { InrPipe } from '../shared/pipes/inr.pipe';
import {
  CATALOG_STATUSES,
  CatalogApiService,
  CatalogCategoriesApiService,
  CatalogCategory,
  CatalogItem,
  CatalogStatus,
  buildCatalogImageHref,
} from './catalog-api.service';
import { AddItemModalComponent } from './add-item-modal.component';
import { CatalogRowMenuComponent } from './catalog-row-menu.component';
import { ViewItemModalComponent } from './view-item-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { deriveApiOrigin } from '@core/services/url.util';

type StatusTabKey = 'all' | CatalogStatus;

interface StatusTab {
  key: StatusTabKey;
  label: string;
}

const STATUS_TABS: StatusTab[] = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Draft' },
  { key: 'published', label: 'Published' },
  { key: 'unpublished', label: 'Unpublished' },
  { key: 'archived', label: 'Archived' },
];

/**
 * Catalog page — bare-minimum product table matching the reference
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
    RouterLink,
    AddItemModalComponent,
    ViewItemModalComponent,
    MobileSelectComponent,
    CatalogRowMenuComponent,
  ],
  templateUrl: './catalog.page.html',
})
export class CatalogPageComponent {
  private readonly api = inject(CatalogApiService);
  private readonly categoriesApi = inject(CatalogCategoriesApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** C2 — Server-managed categories. Replaces the previous client-
   *  derived dropdown that could only see categories on the loaded
   *  page. */
  readonly categories = signal<CatalogCategory[]>([]);

  readonly items = signal<CatalogItem[]>([]);
  readonly total = signal<number>(0);
  readonly statusCounts = signal<Partial<Record<CatalogStatus, number>>>({});
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly TABS = STATUS_TABS;
  readonly activeTab = signal<StatusTabKey>('all');

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

  /** Category options for the dropdown. Prefers the server-managed
   *  category list; falls back to derived-from-items if the categories
   *  fetch hasn't landed yet or the org is still using free-text only. */
  readonly categoryOptions = computed<CatalogCategory[]>(() => {
    const server = this.categories();
    if (server.length > 0) return server;
    const set = new Set<string>();
    for (const i of this.items()) {
      if (i.category) set.add(i.category);
    }
    return [...set].sort().map((name, idx) => ({
      id: `derived:${name}`,
      org_id: '',
      name,
      slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
      description: null,
      icon_emoji: null,
      color_hex: null,
      display_order: idx,
      is_active: true,
      created_at: '',
      updated_at: '',
    }));
  });

  /** `crm-mobile-select` shape for the Category filter — sentinel
   *  "All categories" first, then one entry per category (name is
   *  both value and label, with an optional leading emoji when set). */
  readonly categorySelectOptions = computed<{ value: string; label: string }[]>(() => [
    { value: '', label: 'All categories' },
    ...this.categoryOptions().map((c) => ({
      value: c.name,
      label: c.icon_emoji ? `${c.icon_emoji} ${c.name}` : c.name,
    })),
  ]);

  // --- KPI cards ---

  readonly totalProducts = computed(() => this.total());
  readonly publishedProducts = computed(() => this.statusCounts()['published'] ?? 0);
  readonly draftProducts = computed(() => this.statusCounts()['draft'] ?? 0);
  readonly distinctCategories = computed(() => this.categoryOptions().length);

  /** Total across every status — displayed on the "All" tab. */
  readonly allCount = computed(() =>
    CATALOG_STATUSES.reduce((sum, s) => sum + (this.statusCounts()[s] ?? 0), 0),
  );

  countForTab(tab: StatusTabKey): number {
    if (tab === 'all') return this.allCount();
    return this.statusCounts()[tab] ?? 0;
  }

  selectTab(tab: StatusTabKey): void {
    if (this.activeTab() === tab) return;
    this.activeTab.set(tab);
    this.reload();
  }

  statusBadgeClass(s: CatalogStatus): string {
    switch (s) {
      case 'published':
        return 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20';
      case 'unpublished':
        return 'bg-amber-500/10 text-amber-400 ring-amber-500/20';
      case 'archived':
        return 'bg-surface-2 text-muted ring-zinc-500/20';
      case 'draft':
      default:
        return 'bg-surface-2 text-muted ring-zinc-500/20';
    }
  }
  constructor() {
    this.reload();
    this.reloadCategories();

    // Drive reload off the debounced+distinct `q()` and
    // `categoryFilter()` signals rather than subscribing to
    // valueChanges a second time. Two independent debounced
    // pipelines from the same source raced against the signal
    // write and fired reload twice per keystroke.
    let initial = true;
    effect(() => {
      // Track both signals so the effect re-runs on either change.
      this.q();
      this.categoryFilter();
      if (initial) {
        initial = false;
        return;
      }
      this.reload();
    });
  }

  protected reloadCategories(): void {
    this.categoriesApi
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.categories.set(rows),
        // Silently no-op — the derived fallback in `categoryOptions`
        // keeps the dropdown usable if the categories endpoint fails.
        error: () => this.categories.set([]),
      });
  }

  /** Monotonic request id — bumped on every `reload()`, checked in
   *  the response callback so a slow earlier response can't overwrite
   *  a faster later one when the user types / changes category fast. */
  private reloadSeq = 0;

  protected reload(): void {
    const seq = ++this.reloadSeq;
    this.loading.set(true);
    this.loadError.set(null);
    const tab = this.activeTab();
    const statuses: CatalogStatus[] | undefined =
      tab === 'all' ? undefined : [tab as CatalogStatus];
    this.api
      .list({
        q: this.q() || undefined,
        category: this.categoryFilter() || undefined,
        statuses,
        size: 200,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (seq !== this.reloadSeq) return;
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.statusCounts.set(resp.status_counts ?? {});
          this.loading.set(false);
          this.brokenImages.set(new Set());
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.reloadSeq) return;
          this.items.set([]);
          this.total.set(0);
          this.statusCounts.set({});
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load catalog.');
        },
      });
  }

  /** Optimistic status update from the row menu. On error the menu
   *  emits again with the previous status; on success we still
   *  refetch so the tab counts stay correct. */
  protected applyOptimistic(event: { id: string; status: CatalogStatus }): void {
    this.items.update((rows) =>
      rows.map((r) => (r.id === event.id ? { ...r, status: event.status } : r)),
    );
  }

  /** Row disappeared (delete via row menu). Drop it locally and
   *  refetch to keep tab counts in sync. */
  protected onRowRemoved(id: string): void {
    this.items.update((rows) => rows.filter((r) => r.id !== id));
    this.total.update((n) => Math.max(0, n - 1));
    this.reload();
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

  /** Absolute URL for the backend-served `/files/...` image path. */
  private readonly apiOrigin = deriveApiOrigin();
  protected imageHref(item: CatalogItem): string | null {
    if (!item.image_url) return null;
    if (this.brokenImages().has(item.id)) return null;
    return buildCatalogImageHref(this.apiOrigin, item.image_url, item);
  }

  /** Tracks which product ids have already emitted an ``<img error>``
   *  event this session — those switch to the emoji tile on next
   *  change-detection tick instead of showing the alt-text glyph
   *  Chrome renders for a 404. Common cause is a stale ``image_url``
   *  in the DB where the physical file was cleared (dev shell
   *  ``docker compose down -v``, storage volume reset, orphaned upload
   *  after a container rebuild). Cleared on the next successful
   *  ``list()`` because the row set gets re-read from the API. */
  private readonly brokenImages = signal<Set<string>>(new Set());

  protected onImageError(itemId: string): void {
    this.brokenImages.update((prev) => {
      if (prev.has(itemId)) return prev;
      const next = new Set(prev);
      next.add(itemId);
      return next;
    });
  }

  /** Lookup: category name → CatalogCategory, for `emojiFor()` to
   *  read the operator-picked `icon_emoji` without a per-cell scan. */
  private readonly categoryByName = computed(() => {
    const m = new Map<string, CatalogCategory>();
    for (const c of this.categories()) m.set(c.name, c);
    return m;
  });

  /** Emoji for the product card. Reads the operator-picked
   *  `icon_emoji` off the resolved `CatalogCategory` and falls back
   *  to a generic 📦. Previously hardcoded a furniture-vertical
   *  keyword map here (sofa/bed/chair/dining…), which violated
   *  Rule #1 (core must stay vertical-agnostic — verticals live in
   *  `packs/`). Categories now carry their own icon on
   *  `tbl_catalog_categories.icon_emoji`. */
  protected emojiFor(category: string | null): string {
    if (!category) return '📦';
    return this.categoryByName().get(category)?.icon_emoji ?? '📦';
  }
}
