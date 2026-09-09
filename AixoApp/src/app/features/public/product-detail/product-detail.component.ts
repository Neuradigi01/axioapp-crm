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
import { ActivatedRoute } from '@angular/router';
import { Meta, Title } from '@angular/platform-browser';
import { LucideAngularModule } from 'lucide-angular';

import { assetUrl } from '../shared/asset-url.util';
import {
  PublicCatalogApiService,
  type PublicCatalogDetail,
} from '../shared/public-catalog-api.service';

/**
 * Public catalog product detail page.
 *
 * URL: `/product/{token}`. Every unhappy path (bad/tampered token,
 * non-published, deleted, wrong org) renders the same "Product not
 * available" state — no side channel that would let a scraper
 * distinguish tampered tokens from unpublished items.
 */
@Component({
  selector: 'app-public-product-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './product-detail.component.html',
})
export class PublicProductDetailComponent {
  private readonly api = inject(PublicCatalogApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly titleSvc = inject(Title);
  private readonly meta = inject(Meta);

  protected readonly loading = signal(true);
  protected readonly notFound = signal(false);
  protected readonly detail = signal<PublicCatalogDetail | null>(null);
  protected readonly heroIndex = signal(0);

  /** Every image in one array: primary cover first (when present),
   *  then gallery entries in order. */
  protected readonly orderedImages = computed<string[]>(() => {
    const d = this.detail();
    if (!d) return [];
    const out: string[] = [];
    if (d.image_url) out.push(d.image_url);
    for (const u of d.image_urls ?? []) {
      if (u && u !== d.image_url) out.push(u);
    }
    return out;
  });

  protected readonly currentImage = computed<string | null>(() => {
    const all = this.orderedImages();
    if (all.length === 0) return null;
    const idx = Math.min(this.heroIndex(), all.length - 1);
    return all[idx];
  });

  protected readonly hasMultipleImages = computed(() => this.orderedImages().length > 1);

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const token = params.get('token');
      if (!token) {
        this.notFound.set(true);
        this.loading.set(false);
        return;
      }
      this.loadDetail(token);
    });
  }

  private loadDetail(token: string): void {
    this.loading.set(true);
    this.notFound.set(false);
    this.api
      .getByToken(token)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (d) => {
          this.detail.set(d);
          this.heroIndex.set(0);
          this.loading.set(false);
          this.applyMetaTags(d);
        },
        error: (err: HttpErrorResponse) => {
          this.notFound.set(true);
          this.detail.set(null);
          this.loading.set(false);
          if (err.status !== 404) {
            console.error('public product fetch failed', err);
          }
        },
      });
  }

  private applyMetaTags(d: PublicCatalogDetail): void {
    this.titleSvc.setTitle(`${d.name} – Products`);
    const short = (d.description ?? '').slice(0, 160);
    this.meta.updateTag({ name: 'description', content: short || d.name });
    this.meta.updateTag({ property: 'og:title', content: d.name });
    this.meta.updateTag({ property: 'og:type', content: 'product' });
    if (d.image_url) {
      this.meta.updateTag({ property: 'og:image', content: assetUrl(d.image_url) });
    }
  }

  protected nextImage(): void {
    const total = this.orderedImages().length;
    if (total < 2) return;
    this.heroIndex.update((i) => (i + 1) % total);
  }

  protected prevImage(): void {
    const total = this.orderedImages().length;
    if (total < 2) return;
    this.heroIndex.update((i) => (i - 1 + total) % total);
  }

  protected selectImage(idx: number): void {
    this.heroIndex.set(idx);
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
