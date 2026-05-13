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
import { LucideAngularModule } from 'lucide-angular';

import {
  Review,
  ReviewStats,
  ReviewsApiService,
} from './reviews-api.service';
import { ReviewReplyModalComponent } from './reply-modal.component';

const AUTO_REQUEST_KEY = 'reviews_auto_request';

/**
 * Reviews & Reputation page.
 *
 * Layout (top to bottom):
 *   - 4 KPI cards: avg rating · total · response rate · alerts (≤3★/7d)
 *   - Rating distribution bars (1–5)
 *   - Alerts panel (recent ≤3★ rows the operator should triage)
 *   - Filter strip: All · 1★ · 2★ · 3★ · 4★ · 5★ + auto-request toggle
 *   - Reviews list (cards). Each row: stars · source pill · text ·
 *     reply/escalate buttons (when pending).
 *
 * "Auto-request" toggle persists in localStorage until Step 3.17 ships
 * the Settings backend that will own this preference server-side.
 *
 * The page reads `source` as a free-form string — there is no
 * per-source branch anywhere; new sources land as a styled pill
 * automatically.
 */
@Component({
  selector: 'app-reviews-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReviewReplyModalComponent],
  templateUrl: './reviews.page.html',
})
export class ReviewsPageComponent {
  private readonly api = inject(ReviewsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<Review[]>([]);
  protected readonly stats = signal<ReviewStats | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  /** null = All · 1..5 = star filter */
  protected readonly ratingFilter = signal<number | null>(null);
  protected readonly replyTarget = signal<Review | null>(null);

  protected readonly autoRequest = signal<boolean>(this._readAutoRequest());

  /** Recent ≤3★ rows for the alerts panel — derived from `items`. */
  protected readonly alertRows = computed(() =>
    this.items().filter((r) => r.rating <= 3).slice(0, 5),
  );

  /** Lookup the count for a given rating in the distribution. */
  protected countFor(rating: number): number {
    return (
      this.stats()?.distribution.find((d) => d.rating === rating)?.count ?? 0
    );
  }

  /** Bar width % for the distribution bars — relative to the rating with most counts. */
  protected barWidthPct(rating: number): number {
    const dist = this.stats()?.distribution ?? [];
    const max = dist.reduce((m, d) => Math.max(m, d.count), 0);
    if (max === 0) return 0;
    return Math.round((this.countFor(rating) / max) * 100);
  }

  protected stars(n: number): string {
    return '★★★★★'.slice(0, n) + '☆☆☆☆☆'.slice(0, 5 - n);
  }

  protected roundedAvg(avg: number): number {
    return Math.round(avg);
  }

  protected statusBadge(status: Review['status']): {
    label: string;
    cls: string;
  } {
    switch (status) {
      case 'replied':
        return {
          label: 'Replied',
          cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
        };
      case 'escalated':
        return {
          label: 'Escalated',
          cls: 'bg-rose-50 text-rose-700 ring-rose-200',
        };
      default:
        return {
          label: 'Pending reply',
          cls: 'bg-amber-50 text-amber-700 ring-amber-200',
        };
    }
  }

  /**
   * Source pill colour — derived from a deterministic hash of the
   * source string so unknown sources still get a stable colour. No
   * hardcoded source-specific UI per the self-check.
   */
  protected sourcePill(source: string): string {
    const palette = [
      'bg-blue-50 text-blue-700 ring-blue-200',
      'bg-violet-50 text-violet-700 ring-violet-200',
      'bg-sky-50 text-sky-700 ring-sky-200',
      'bg-emerald-50 text-emerald-700 ring-emerald-200',
      'bg-rose-50 text-rose-700 ring-rose-200',
      'bg-amber-50 text-amber-700 ring-amber-200',
      'bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200',
    ];
    let h = 0;
    for (const c of source) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }

  constructor() {
    this.refresh();
    // Persist the toggle whenever it flips.
    effect(() => {
      try {
        localStorage.setItem(
          AUTO_REQUEST_KEY,
          this.autoRequest() ? '1' : '0',
        );
      } catch {
        /* localStorage might be unavailable — silently ignore */
      }
    });
  }

  protected setRating(r: number | null): void {
    this.ratingFilter.set(r);
    this.reloadList();
  }

  protected refresh(): void {
    this.reloadStats();
    this.reloadList();
  }

  protected openReply(review: Review): void {
    this.replyTarget.set(review);
  }

  protected closeReply(): void {
    this.replyTarget.set(null);
  }

  protected onReplied(updated: Review): void {
    this.items.update((rows) =>
      rows.map((r) => (r.id === updated.id ? updated : r)),
    );
    this.replyTarget.set(null);
    this.reloadStats();
  }

  protected escalate(review: Review): void {
    const ok = window.confirm(
      `Escalate this ${review.rating}★ review for owner attention?`,
    );
    if (!ok) return;
    this.api
      .escalate(review.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) =>
            rows.map((r) => (r.id === updated.id ? updated : r)),
          );
          this.reloadStats();
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(
            this._extract(err) ?? 'Could not escalate review.',
          );
        },
      });
  }

  protected toggleAutoRequest(): void {
    this.autoRequest.update((v) => !v);
  }

  private reloadList(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const query =
      this.ratingFilter() !== null
        ? { rating: this.ratingFilter() as number, size: 200 }
        : { size: 200 };
    this.api
      .list(query)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            this._extract(err) ?? 'Could not load reviews.',
          );
        },
      });
  }

  private reloadStats(): void {
    this.api
      .stats()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => this.stats.set(s),
        error: () => this.stats.set(null),
      });
  }

  private _readAutoRequest(): boolean {
    try {
      return localStorage.getItem(AUTO_REQUEST_KEY) === '1';
    } catch {
      return false;
    }
  }

  private _extract(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
