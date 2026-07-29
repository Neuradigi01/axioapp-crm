import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';

import { InrPipe } from '../../features/user/core/shared/pipes/inr.pipe';
import { StaffPerformance, StaffPortalApiService } from '../staff-portal-api.service';
import { StaffSessionService } from '../staff-session.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * My Dashboard — landing tab after PIN login. Six KPI cards from
 * `GET /staff-portal/me/performance` (leads converted, leads active,
 * sales-MTD, monthly target, target progress, rating, commission).
 */
@Component({
  selector: 'app-my-dashboard-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InrPipe],
  templateUrl: './my-dashboard.page.html',
})
export class MyDashboardPageComponent {
  private readonly api = inject(StaffPortalApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly session = inject(StaffSessionService);

  protected readonly perf = signal<StaffPerformance | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .performance()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.perf.set(p);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.perf.set(null);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load your dashboard.');
        },
      });
  }

  protected progressWidth(p: StaffPerformance): number {
    const v = p.target_progress_pct;
    if (v === null) return 0;
    return v > 100 ? 100 : v;
  }
}
