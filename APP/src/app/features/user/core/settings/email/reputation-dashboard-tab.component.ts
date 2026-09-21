/**
 * Reputation dashboard tab (tasks/email-reputation-warmup Step 7).
 *
 * Owner-only surface for per-envelope reputation. Sits alongside
 * Sending Domains + Inbound Addresses in Settings → Workspace.
 *
 * Behaviour:
 *
 *   * On enter — fetches once via ``ReputationService.list()``.
 *   * Poll every 30 s while the tab is mounted so counter bumps
 *     from the events-webhook (Step 3) land without a manual reload.
 *   * Second-level tick for the ``blocked_until`` countdown inside
 *     each card. Cleared on destroy.
 *
 * Empty state — the backend synthesises a pristine ``platform_from``
 * row for every org, so ``rows.length === 0`` only happens on a
 * backend regression or the loading path.
 */
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { interval, startWith } from 'rxjs';
import { extractApiError } from '@core/services/api-error.util';

import { EnvelopeReputationCardComponent } from './envelope-reputation-card.component';
import type { EnvelopeReputation } from './reputation.service';
import { ReputationService } from './reputation.service';

/** Polling cadence — matches other beat-driven tabs (Sending Domains
 * verify status). 30s is fast enough that a shed transition lands
 * within one refresh; slower would leave a stale card visible for
 * over a minute. */
const REFRESH_INTERVAL_MS = 30_000;

/** Second-level tick for the blocked-until countdown. Cheap — just
 * bumps a signal that the card templates re-render off. */
const COUNTDOWN_TICK_MS = 1_000;

@Component({
  selector: 'app-reputation-dashboard-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EnvelopeReputationCardComponent, LucideAngularModule],
  templateUrl: './reputation-dashboard-tab.component.html',
})
export class ReputationDashboardTabComponent {
  private readonly api = inject(ReputationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly rows = signal<EnvelopeReputation[]>([]);
  readonly nowMs = signal(Date.now());

  constructor() {
    // 30s poll for the row data.
    interval(REFRESH_INTERVAL_MS)
      .pipe(startWith(0), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());
    // 1s tick for the blocked-until countdown inside each card.
    interval(COUNTDOWN_TICK_MS)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.nowMs.set(Date.now()));
  }

  private reload(): void {
    // Don't flip loading on the poll path — the visible content
    // shouldn't blink every 30s. Only the first fetch shows the
    // spinner.
    const firstLoad = this.rows().length === 0;
    if (firstLoad) this.loading.set(true);
    this.loadError.set(null);
    this.api.list().subscribe({
      next: (rows) => {
        this.rows.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.loadError.set(extractApiError(err) ?? 'Could not load reputation dashboard.');
        this.loading.set(false);
      },
    });
  }
}
