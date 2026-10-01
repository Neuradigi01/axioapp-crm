import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { Subscription } from 'rxjs';

import { Review, ReviewStats, ReviewsApiService } from './reviews-api.service';
import { ReviewReplyModalComponent } from './reply-modal.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { FurnitureAuthService } from '../auth/auth.service';
import { SettingsApiService } from '../settings/settings-api.service';
import { extractApiError } from '@core/services/api-error.util';

/** Reviews per page; "Load more" appends the next page. */
const PAGE_SIZE = 50;
/** Rows shown in the "Needs attention" panel. */
const ATTENTION_ROWS = 5;
/** Highest star rating that counts as "needs attention". */
const ATTENTION_MAX_RATING = 3;

/**
 * Reviews & Reputation page.
 *
 * Layout (top to bottom):
 *   - 4 KPI cards: avg rating · total · response rate · alerts (≤3★/7d)
 *   - Rating distribution bars (1–5)
 *   - "Needs attention": the newest unanswered ≤3★ reviews — fetched on
 *     its own so it never depends on the list's star filter
 *   - Filter strip: All · 5★ … 1★ + the org-wide auto-request setting
 *   - Reviews list (cards) with Load more. Reply is offered on every
 *     review without a reply (pending or escalated); Escalate only on
 *     pending ones.
 *
 * The page reads `source` as a free-form string — there is no
 * per-source branch anywhere; new sources land as a styled pill
 * automatically.
 */
@Component({
  selector: 'app-reviews-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReviewReplyModalComponent, ConfirmDialogComponent],
  templateUrl: './reviews.page.html',
})
export class ReviewsPageComponent {
  private readonly api = inject(ReviewsApiService);
  private readonly settingsApi = inject(SettingsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<Review[]>([]);
  protected readonly total = signal(0);
  protected readonly stats = signal<ReviewStats | null>(null);
  protected readonly statsError = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadingMore = signal(false);
  protected readonly loadError = signal<string | null>(null);
  /** Errors from row actions (escalate) — kept separate from the list
   *  load error so a list refresh doesn't wipe them. */
  protected readonly actionError = signal<string | null>(null);

  /** null = All · 1..5 = star filter */
  protected readonly ratingFilter = signal<number | null>(null);
  protected readonly replyTarget = signal<Review | null>(null);

  protected readonly attentionRows = signal<Review[]>([]);
  protected readonly attentionTotal = signal(0);

  /** Org-wide auto-request setting (server-side). Null until loaded or
   *  when the caller can't read settings — the toggle is then hidden. */
  protected readonly autoRequest = signal<boolean | null>(null);
  protected readonly autoRequestSaving = signal(false);
  protected readonly canEditAutoRequest = this.auth.hasPermission('settings.write');

  protected readonly escalateTarget = signal<Review | null>(null);
  protected readonly escalating = signal(false);

  private page = 1;
  private listSub: Subscription | null = null;

  protected hasMore(): boolean {
    return this.items().length < this.total();
  }

  /** Lookup the count for a given rating in the distribution. */
  protected countFor(rating: number): number {
    return this.stats()?.distribution.find((d) => d.rating === rating)?.count ?? 0;
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

  /** Reply is possible on any review without a reply — escalating a
   *  review must not take away the option to answer it. */
  protected canReply(r: Review): boolean {
    return !r.reply_text && r.status !== 'replied';
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
          cls: 'bg-red-500/10 text-red-400 ring-red-500/20',
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
      'bg-red-500/10 text-red-400 ring-red-500/20',
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
    this.loadAutoRequest();
  }

  protected setRating(r: number | null): void {
    this.ratingFilter.set(r);
    this.reloadList();
  }

  protected refresh(): void {
    this.reloadStats();
    this.reloadAttention();
    this.reloadList();
  }

  protected openReply(review: Review): void {
    this.replyTarget.set(review);
  }

  protected closeReply(): void {
    this.replyTarget.set(null);
  }

  protected onReplied(updated: Review): void {
    this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
    this.replyTarget.set(null);
    this.reloadStats();
    this.reloadAttention();
  }

  protected askEscalate(review: Review): void {
    this.actionError.set(null);
    this.escalateTarget.set(review);
  }

  protected cancelEscalate(): void {
    if (this.escalating()) return;
    this.escalateTarget.set(null);
  }

  protected confirmEscalate(): void {
    const review = this.escalateTarget();
    if (!review || this.escalating()) return;
    this.escalating.set(true);
    this.api
      .escalate(review.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.escalating.set(false);
          this.escalateTarget.set(null);
          this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.reloadStats();
          this.reloadAttention();
        },
        error: (err: HttpErrorResponse) => {
          this.escalating.set(false);
          this.escalateTarget.set(null);
          this.actionError.set(extractApiError(err) ?? 'Could not escalate review.');
        },
      });
  }

  /** Flip the org-wide setting; roll back the toggle if the save fails. */
  protected toggleAutoRequest(): void {
    const current = this.autoRequest();
    if (current === null || !this.canEditAutoRequest || this.autoRequestSaving()) return;
    const next = !current;
    this.autoRequest.set(next);
    this.autoRequestSaving.set(true);
    this.settingsApi
      .patch({ reviews_auto_request_enabled: next })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.autoRequestSaving.set(false);
          this.autoRequest.set(s.reviews_auto_request_enabled);
        },
        error: (err: HttpErrorResponse) => {
          this.autoRequestSaving.set(false);
          this.autoRequest.set(current);
          this.actionError.set(extractApiError(err) ?? 'Could not save the auto-request setting.');
        },
      });
  }

  protected loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.fetchPage(this.page + 1);
  }

  protected retryStats(): void {
    this.reloadStats();
  }

  private reloadList(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.fetchPage(1);
  }

  /** Newest request wins — switching the star filter cancels the
   *  previous request so its rows can't land under the new filter. */
  private fetchPage(page: number): void {
    const rating = this.ratingFilter();
    if (page > 1) this.loadingMore.set(true);
    this.listSub?.unsubscribe();
    this.listSub = this.api
      .list({ rating: rating ?? undefined, page, size: PAGE_SIZE })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.page = page;
          this.items.update((rows) => (page === 1 ? resp.items : [...rows, ...resp.items]));
          this.total.set(resp.total);
          this.loading.set(false);
          this.loadingMore.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (page === 1) {
            this.items.set([]);
            this.total.set(0);
          }
          this.loading.set(false);
          this.loadingMore.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load reviews.');
        },
      });
  }

  private reloadStats(): void {
    this.statsError.set(null);
    this.api
      .stats()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => this.stats.set(s),
        error: (err: HttpErrorResponse) => {
          this.stats.set(null);
          this.statsError.set(extractApiError(err) ?? 'Could not load the rating summary.');
        },
      });
  }

  /** Newest unanswered ≤3★ reviews — independent of the list filter. */
  private reloadAttention(): void {
    this.api
      .list({
        status: 'pending_reply',
        max_rating: ATTENTION_MAX_RATING,
        page: 1,
        size: ATTENTION_ROWS,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.attentionRows.set(resp.items);
          this.attentionTotal.set(resp.total);
        },
        error: () => {
          this.attentionRows.set([]);
          this.attentionTotal.set(0);
        },
      });
  }

  private loadAutoRequest(): void {
    if (!this.auth.hasPermission('settings.read')) return;
    this.settingsApi
      .get()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => this.autoRequest.set(s.reviews_auto_request_enabled),
        // No access / transient failure → the toggle stays hidden.
        error: () => this.autoRequest.set(null),
      });
  }
}
