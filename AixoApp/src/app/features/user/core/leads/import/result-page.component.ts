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
import { Subscription, interval } from 'rxjs';
import { startWith } from 'rxjs/operators';

import { ImportsApiService, LeadImport, LeadImportStatus } from './imports-api.service';

/**
 * `/user/leads/import/:id/result` — post-commit dashboard.
 *
 * Polls the import row every 2 seconds while `mapping_committed` or
 * `processing`. On a terminal status (`completed` / `failed` /
 * `cancelled`), polling stops and the page renders:
 *
 *   - counts card (imported / duplicates skipped / errors);
 *   - "Download error report" button when the job produced errors;
 *   - "Back to leads" CTA.
 *
 * In dev (CELERY_ENABLED=false), the commit endpoint awaits the
 * processor inline so by the time the user lands here the row may
 * already be `completed`. The polling code handles that case
 * cleanly — first tick fetches, sees a terminal status, stops.
 */

const POLL_INTERVAL_MS = 2000;

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

  private pollSub: Subscription | null = null;

  constructor() {
    if (!this.importId) {
      this.loadError.set('No import id in the route.');
      return;
    }
    this.startPolling();
  }

  private startPolling(): void {
    // First-tick-immediate via `startWith(0)` so the UI fills as soon
    // as the page loads; subsequent ticks fire every 2s. We stop the
    // subscription as soon as the row reaches a terminal status.
    this.pollSub = interval(POLL_INTERVAL_MS)
      .pipe(startWith(0), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.fetch());
  }

  private fetch(): void {
    this.api
      .get(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.importRow.set(row);
          if (TERMINAL_STATUSES.has(row.status)) {
            this.pollSub?.unsubscribe();
            this.pollSub = null;
          }
        },
        error: () => {
          this.loadError.set('Could not load this import.');
          this.pollSub?.unsubscribe();
          this.pollSub = null;
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
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `import-${this.importId}-errors.csv`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        },
        error: () => this.downloading.set(false),
      });
  }
}
