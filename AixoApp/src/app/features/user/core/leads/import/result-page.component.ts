import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ImportsApiService, LeadImport, LeadImportStatus } from './imports-api.service';

/**
 * `/user/leads/import/:id/result` — post-commit dashboard.
 *
 * Polls the import row every 2 seconds while `mapping_committed` or
 * `processing`. On a terminal status (`completed` / `failed` /
 * `cancelled`), polling stops and the page renders:
 *
 *   - counts card (imported / duplicates skipped / errors);
 *   - per-category reason breakdown (e.g. "50× invalid date …")
 *     under the counters that had non-empty `error_reasons` /
 *     `skipped_reasons` / `warning_reasons` maps in the response;
 *   - "Download error report" button when the job produced errors;
 *   - "Download duplicates report" button when the job skipped rows;
 *   - "Download warnings report" button when the job substituted
 *     out-of-vocabulary values (e.g. unknown pipeline_stage → default);
 *   - "Back to leads" CTA.
 *
 * In dev (CELERY_ENABLED=false), the commit endpoint awaits the
 * processor inline so by the time the user lands here the row may
 * already be `completed`. The polling code handles that case
 * cleanly — first tick fetches, sees a terminal status, stops.
 */

// Backoff schedule for the status poll. First few ticks are quick so
// small imports (dev inline, sub-second Celery hop) feel instant; the
// interval then grows so a genuinely long-running 10-min bulk import
// isn't hammered with 300 requests. Cap at 30s — long enough to spare
// the API, short enough that a completed import doesn't feel stuck.
const POLL_BACKOFF_MS: readonly number[] = [2000, 2000, 5000, 5000, 10000, 15000, 30000];
const POLL_MAX_MS = POLL_BACKOFF_MS[POLL_BACKOFF_MS.length - 1];

const TERMINAL_STATUSES = new Set<LeadImportStatus>(['completed', 'failed', 'cancelled']);

@Component({
  selector: 'app-import-result-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './result-page.component.html',
})
export class ResultPageComponent {
  private readonly api = inject(ImportsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly importId = this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly importRow = signal<LeadImport | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly downloading = signal(false);
  protected readonly downloadingSkipped = signal(false);
  protected readonly downloadingWarnings = signal(false);

  protected readonly isTerminal = computed(() => {
    const row = this.importRow();
    return row !== null && TERMINAL_STATUSES.has(row.status);
  });

  protected readonly statusLabel = computed(() => {
    const status = this.importRow()?.status;
    switch (status) {
      case 'mapping_committed':
        return 'Queued';
      case 'processing':
        return 'Processing…';
      case 'completed':
        return 'Completed';
      case 'failed':
        return 'Failed';
      case 'cancelled':
        return 'Cancelled';
      default:
        return 'Loading…';
    }
  });

  protected readonly counts = computed(() => this.importRow()?.counts ?? null);

  protected readonly hasErrors = computed(() => {
    const c = this.counts();
    return c !== null && (c.errors ?? 0) > 0 && !!this.importRow()?.error_report_path;
  });

  protected readonly hasSkipped = computed(() => {
    const c = this.counts();
    return c !== null && (c.duplicates_skipped ?? 0) > 0 && !!this.importRow()?.skipped_report_path;
  });

  protected readonly hasWarnings = computed(() => {
    const c = this.counts();
    return c !== null && (c.warnings ?? 0) > 0 && !!this.importRow()?.warnings_report_path;
  });

  /** Error reasons sorted count-descending for a stable readout order.
   * Empty when the processor didn't emit any bucketed reasons (legacy
   * completed imports from before the reason-tracking work). */
  protected readonly errorReasonList = computed(() =>
    this.reasonList(this.counts()?.error_reasons),
  );

  /** Same shape as `errorReasonList`, for the "duplicates skipped" tally. */
  protected readonly skippedReasonList = computed(() =>
    this.reasonList(this.counts()?.skipped_reasons),
  );

  /** Same shape, for the "imported with a value fallback" tally. */
  protected readonly warningReasonList = computed(() =>
    this.reasonList(this.counts()?.warning_reasons),
  );

  private reasonList(
    bucket: Record<string, number> | undefined,
  ): { label: string; count: number }[] {
    if (!bucket) return [];
    return Object.entries(bucket)
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);
  }

  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTick = 0;

  constructor() {
    if (!this.importId) {
      this.loadError.set('No import id in the route.');
      return;
    }
    // Immediate first fetch — subsequent ticks are scheduled with a
    // backoff so a 10-min import doesn't fire 300 status polls.
    this.fetch();
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  private scheduleNextPoll(): void {
    const delay = POLL_BACKOFF_MS[this.pollTick] ?? POLL_MAX_MS;
    this.pollTick += 1;
    this.pollTimer = setTimeout(() => this.fetch(), delay);
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private fetch(): void {
    this.api
      .get(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.importRow.set(row);
          if (TERMINAL_STATUSES.has(row.status)) {
            this.stopPolling();
            return;
          }
          this.scheduleNextPoll();
        },
        error: () => {
          this.loadError.set('Could not load this import.');
          this.stopPolling();
        },
      });
  }

  protected downloadErrors(): void {
    if (!this.hasErrors() || this.downloading()) return;
    this.downloading.set(true);
    this.api
      .downloadErrors(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloading.set(false);
          this.triggerDownload(blob, `import-${this.importId}-errors.csv`);
        },
        error: () => this.downloading.set(false),
      });
  }

  protected downloadSkipped(): void {
    if (!this.hasSkipped() || this.downloadingSkipped()) return;
    this.downloadingSkipped.set(true);
    this.api
      .downloadSkipped(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloadingSkipped.set(false);
          this.triggerDownload(blob, `import-${this.importId}-skipped.csv`);
        },
        error: () => this.downloadingSkipped.set(false),
      });
  }

  protected downloadWarnings(): void {
    if (!this.hasWarnings() || this.downloadingWarnings()) return;
    this.downloadingWarnings.set(true);
    this.api
      .downloadWarnings(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloadingWarnings.set(false);
          this.triggerDownload(blob, `import-${this.importId}-warnings.csv`);
        },
        error: () => this.downloadingWarnings.set(false),
      });
  }

  private triggerDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
}
