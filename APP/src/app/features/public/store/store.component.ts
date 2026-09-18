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
  type PublicStore,
} from '../shared/public-catalog-api.service';

/**
 * Public storefront — the whole-org catalog view behind a Fernet
 * token. URL: `/store/:token`.
 *
 * Distinct from `/catalog?org=<slug>` (slug-based, also public): the
 * token variant lets the owner mint a share URL without ever exposing
 * the org slug, and rotating the Fernet key invalidates every
 * outstanding storefront link at once.
 *
 * Client-side filters (search + category chip + sort) run against the
 * already-fetched list — no pagination round-trips. The backend
 * scopes to `status='published'` for the token's org.
 */
@Component({
  selector: 'app-public-store',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, LucideAngularModule],
  templateUrl: './store.component.html',
})
export class PublicStoreComponent {
  private readonly api = inject(PublicCatalogApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly titleSvc = inject(Title);
  private readonly meta = inject(Meta);

  protected readonly token = signal<string | null>(null);
  protected readonly orgName = signal<string>('');
  protected readonly items = signal<PublicCatalogCard[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly searchControl = new FormControl('', { nonNullable: true });
  protected readonly search = signal<string>('');
  protected readonly activeCategory = signal<string | null>(null);
  protected readonly sortMode = signal<'default' | 'price_asc' | 'price_desc'>('default');

  /** Distinct category chips derived from the loaded items — ordered
   *  by first-appearance, so "All" leads and the org's own item order
   *  drives the rest. */
  protected readonly categories = computed<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of this.items()) {
      const cat = (c.category || '').trim();
      if (cat && !seen.has(cat)) {
        seen.add(cat);
        out.push(cat);
      }
    }
    return out;
  });

  protected readonly filteredItems = computed<PublicCatalogCard[]>(() => {
    const q = this.search().trim().toLowerCase();
    const cat = this.activeCategory();
    let rows = this.items().slice();
    if (cat) rows = rows.filter((c) => (c.category || '').trim() === cat);
    if (q) {
      rows = rows.filter((c) => {
        const hay = [c.name, c.sku, c.category, c.short_description]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        return hay.includes(q);
      });
    }
    const mode = this.sortMode();
    if (mode !== 'default') {
      rows.sort((a, b) => {
        const av = typeof a.price === 'string' ? Number(a.price) : a.price;
        const bv = typeof b.price === 'string' ? Number(b.price) : b.price;
        const ax = Number.isFinite(av) ? av : 0;
        const bx = Number.isFinite(bv) ? bv : 0;
        return mode === 'price_asc' ? ax - bx : bx - ax;
      });
    }
    return rows;
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const token = params.get('token')?.trim() || null;
      this.token.set(token);
      if (token) this.reload(token);
      else {
        this.items.set([]);
        this.loading.set(false);
      }
    });

    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.search.set(value));
  }

  private reload(token: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getStoreByToken(token)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp: PublicStore) => {
          this.orgName.set(resp.org_name || 'Store');
          this.items.set(resp.items);
          this.loading.set(false);
          const title = `${resp.org_name || 'Store'} — Catalog`;
          this.titleSvc.setTitle(title);
          this.meta.updateTag({
            name: 'description',
            content: `Browse every product from ${resp.org_name || 'this store'}.`,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          if (err.status === 404) {
            this.loadError.set('This store link is no longer available.');
          } else {
            this.loadError.set('Could not load the store. Please refresh the page.');
          }
        },
      });
  }

  protected pickCategory(cat: string | null): void {
    this.activeCategory.set(cat);
  }

  protected setSort(mode: 'default' | 'price_asc' | 'price_desc'): void {
    this.sortMode.set(mode);
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

  protected initials(name: string): string {
    const trimmed = name.trim();
    if (!trimmed) return 'S';
    const parts = trimmed.split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
}
