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
  PublicPropertyApiService,
  type PublicPropertyDetail,
} from '../shared/public-property-api.service';

/**
 * Public property detail page.
 *
 * URL: `/property/{token}`. Every unhappy path (bad / tampered
 * token, non-published, deleted) renders the same "Property not
 * available" state — no side channel that would let a scraper
 * distinguish tampered tokens from unpublished properties.
 */
@Component({
  selector: 'app-public-property-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './property-detail.component.html',
})
export class PublicPropertyDetailComponent {
  private readonly api = inject(PublicPropertyApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly titleSvc = inject(Title);
  private readonly meta = inject(Meta);

  protected readonly loading = signal(true);
  protected readonly notFound = signal(false);
  protected readonly detail = signal<PublicPropertyDetail | null>(null);
  protected readonly heroIndex = signal(0);

  /** Ordered images — featured first, then by display_order. */
  protected readonly orderedImages = computed(() => {
    const d = this.detail();
    if (!d) return [];
    const featured = d.images.filter((i) => i.is_featured);
    const rest = d.images
      .filter((i) => !i.is_featured)
      .sort((a, b) => a.display_order - b.display_order);
    return [...featured, ...rest];
  });

  protected readonly currentImage = computed(() => {
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
            // Non-404 errors (network, 500) still show the same
            // "not available" page — we don't leak backend errors
            // to visitors. Console log for ops.
            console.error('public detail fetch failed', err);
          }
        },
      });
  }

  private applyMetaTags(d: PublicPropertyDetail): void {
    const title = `${d.title} – Properties`;
    this.titleSvc.setTitle(title);
    const short = (d.description ?? '').slice(0, 160);
    this.meta.updateTag({ name: 'description', content: short || d.title });
    this.meta.updateTag({ property: 'og:title', content: d.title });
    this.meta.updateTag({ property: 'og:type', content: 'product' });
    if (d.featured_image_url) {
      this.meta.updateTag({ property: 'og:image', content: d.featured_image_url });
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

  protected formatPrice(price: string | number | null, currency: string): string {
    if (price === null || price === undefined) return 'Price on request';
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

  protected labelForType(key: string | null): string {
    if (!key) return '';
    return key
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  }

  protected mailtoLink(): string | null {
    const d = this.detail();
    if (!d?.contact_email) return null;
    const subject = encodeURIComponent(`Enquiry: ${d.title}`);
    return `mailto:${d.contact_email}?subject=${subject}`;
  }

  protected telLink(): string | null {
    const d = this.detail();
    if (!d?.contact_phone) return null;
    return `tel:${d.contact_phone.replace(/\s+/g, '')}`;
  }

  protected imgSrc(url: string | null | undefined): string {
    return assetUrl(url);
  }
}
