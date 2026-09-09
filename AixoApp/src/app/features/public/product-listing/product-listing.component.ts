import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Meta, Title } from '@angular/platform-browser';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { assetUrl } from '../shared/asset-url.util';
import {
  PublicCatalogApiService,
  type PublicCatalogCard,
} from '../shared/public-catalog-api.service';

/**
 * Public catalog grid.
 *
 * URL: `/catalog?org=<slug>`. Missing `org` renders a friendly
 * hint rather than a broken grid. Unknown slug renders an empty
 * grid (matches the backend's scraper-safe behaviour — no 404
 * status difference).
 *
 * Client-side search filters on name/SKU/category. Backend already
 * scopes to `status='published'` for the requested org.
 */
@Component({
  selector: 'app-public-product-listing',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, LucideAngularModule],
  templateUrl: './product-listing.component.html',
})
export class PublicProductListingComponent {
  private readonly api = inject(PublicCatalogApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly titleSvc = inject(Title);
  private readonly meta = inject(Meta);

  protected readonly orgSlug = signal<string | null>(null);
  protected readonly items = signal<PublicCatalogCard[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly searchControl = new FormControl('', { nonNullable: true });
  protected readonly search = signal<string>('');

  protected readonly filteredItems = computed(() => {
    const q = this.search().trim().toLowerCase();
    if (!q) return this.items();
    return this.items().filter((c) => {
      const haystack = [c.name, c.sku, c.category, c.short_description]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  });

  constructor() {
    this.titleSvc.setTitle('Products');
    this.meta.updateTag({
      name: 'description',
      content: 'Browse the latest product catalog.',
    });

    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const slug = params.get('org')?.trim() || null;
      this.orgSlug.set(slug);
      if (slug) this.reload();
      else this.items.set([]);
    });

    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.search.set(value));
  }

  private reload(): void {
    const slug = this.orgSlug();
    if (!slug) return;
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listPublic(slug)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (cards) => {
          this.items.set(cards);
          this.loading.set(false);
        },
        error: (_err: HttpErrorResponse) => {
          this.loadError.set('Could not load products. Please refresh the page.');
          this.loading.set(false);
        },
      });
  }

  protected formatPrice(price: string | number, currency: string): string {
    const num = typeof price === 'string' ? Number(price) : price;
    if (!Number.isFinite(num)) return 'Price on request';
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

  protected imgSrc(url: string | null | undefined): string {
    return assetUrl(url);
  }
}
