import { CommonModule, DatePipe, PercentPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  ABStatsResponse,
  WorkflowsApiService,
} from '../workflows-api.service';


/**
 * Live A/B-test banner. Polls `/workflows/{id}/ab-stats` once a
 * minute while mounted; renders the per-variant conversion rates +
 * sample sizes + time-until-decision + (post-decision) the winner
 * call. The "Compare" button routes to the full comparison page.
 */


const REFRESH_INTERVAL_MS = 60_000;


@Component({
  selector: 'app-ab-stats-banner',
  standalone: true,
  imports: [
    CommonModule,
    DatePipe,
    PercentPipe,
    RouterLink,
    LucideAngularModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ab-stats-banner.component.html',
})
export class ABStatsBannerComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly workflowId = input.required<string>();

  readonly stats = signal<ABStatsResponse | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly unpair = output<void>();

  readonly winnerCalled = computed(
    () => this.stats()?.decided_at != null,
  );

  readonly aPercent = computed(() => this.stats()?.a_rate ?? 0);
  readonly bPercent = computed(() => this.stats()?.b_rate ?? 0);

  constructor() {
    effect(() => {
      void this.workflowId();
      this.refresh();
    });

    const timer = window.setInterval(() => this.refresh(), REFRESH_INTERVAL_MS);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  refresh(): void {
    this.api
      .getABStats(this.workflowId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (stats) => {
          this.stats.set(stats);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Stats unavailable.');
          this.loading.set(false);
        },
      });
  }

  winnerLabel(): string {
    const w = this.stats()?.winner;
    if (w === 'a') return 'Variant A';
    if (w === 'b') return 'Variant B';
    return '';
  }
}
