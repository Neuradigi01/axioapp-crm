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
  PublicPropertyApiService,
  type PublicPropertyCard,
  type PublicPropertyStore,
} from '../shared/public-property-api.service';

/**
 * Public real-estate listings storefront — the whole-org view behind
 * a Fernet token. URL: `/listings/:token`.
 *
 * Distinct from `/properties?org=<slug>` (slug-based, also public):
 * the token variant lets the owner mint a share URL without ever
 * exposing the org slug, and rotating the Fernet key invalidates
 * every outstanding storefront link at once.
 *
 * Client-side filters (search + city chip + type chip + price sort)
 * run against the already-fetched list — no pagination round-trips.
 * The backend scopes to `status='published'` for the token's org.
 */
@Component({
  selector: 'app-public-listings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, LucideAngularModule],
  templateUrl: './listings.component.html',
})
export class PublicListingsComponent {
  private readonly api = inject(PublicPropertyApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly titleSvc = inject(Title);
  private readonly meta = inject(Meta);

  protected readonly token = signal<string | null>(null);
  protected readonly orgName = signal<string>('');
  protected readonly items = signal<PublicPropertyCard[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly searchControl = new FormControl('', { nonNullable: true });
  protected readonly search = signal<string>('');
  protected readonly activeCity = signal<string | null>(null);
  protected readonly activeType = signal<string | null>(null);
  protected readonly sortMode = signal<'default' | 'price_asc' | 'price_desc'>('default');

  /** Cities present in the loaded set — first-appearance order. */
  protected readonly cities = computed<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of this.items()) {
      const city = (c.city || '').trim();
      if (city && !seen.has(city)) {
        seen.add(city);
        out.push(city);
      }
    }
    return out;
  });

  /** Property types present in the loaded set — first-appearance order. */
  protected readonly types = computed<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of this.items()) {
      const t = (c.property_type || '').trim();
      if (t && !seen.has(t)) {
        seen.add(t);
        out.push(t);
      }
    }
    return out;
  });

  protected readonly filteredItems = computed<PublicPropertyCard[]>(() => {
    const q = this.search().trim().toLowerCase();
    const city = this.activeCity();
    const type = this.activeType();
    let rows = this.items().slice();
    if (city) rows = rows.filter((c) => (c.city || '').trim() === city);
    if (type) rows = rows.filter((c) => (c.property_type || '').trim() === type);
    if (q) {
      rows = rows.filter((c) => {
        const hay = [c.title, c.city, c.state, c.property_type, c.short_description]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        return hay.includes(q);
      });
    }
    const mode = this.sortMode();
    if (mode !== 'default') {
      rows.sort((a, b) => {
        const av = a.price == null ? 0 : typeof a.price === 'string' ? Number(a.price) : a.price;
        const bv = b.price == null ? 0 : typeof b.price === 'string' ? Number(b.price) : b.price;
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
      .getListingsByToken(token)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp: PublicPropertyStore) => {
          this.orgName.set(resp.org_name || 'Listings');
          this.items.set(resp.items);
          this.loading.set(false);
          const title = `${resp.org_name || 'Listings'} — Properties`;
          this.titleSvc.setTitle(title);
          this.meta.updateTag({
            name: 'description',
            content: `Browse every property from ${resp.org_name || 'this broker'}.`,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          if (err.status === 404) {
            this.loadError.set('This listings link is no longer available.');
          } else {
            this.loadError.set('Could not load the listings. Please refresh the page.');
          }
        },
      });
  }

  protected pickCity(city: string | null): void {
    this.activeCity.set(city);
  }

  protected pickType(type: string | null): void {
    this.activeType.set(type);
  }

  protected setSort(mode: 'default' | 'price_asc' | 'price_desc'): void {
    this.sortMode.set(mode);
  }

  protected formatPrice(price: string | number | null, currency: string): string {
    if (price == null) return 'Price on request';
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
    if (!trimmed) return 'L';
    const parts = trimmed.split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  protected typeLabel(key: string): string {
    // Backend stores enum-ish keys like `apartment`, `commercial_office`.
    // Turn them into "Apartment" / "Commercial Office" for the chip UI.
    return key
      .split('_')
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  }
}
