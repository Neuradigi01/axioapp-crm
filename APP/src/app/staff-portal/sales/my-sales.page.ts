import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';

import { InrPipe } from '../../features/user/core/shared/pipes/inr.pipe';
import { extractApiError } from '@core/services/api-error.util';
import {
  StaffPerformance,
  StaffPortalApiService,
} from '../staff-portal-api.service';

/**
 * My Sales â€” leads/conversion + sales-MTD snapshot for the signed-in
 * staff. `sales` is the same Phase-5-placeholder zero today; the page
 * is shaped so the moment invoices ship the numbers will appear here
 * without UI changes.
 */
@Component({
  selector: 'app-my-sales-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InrPipe],
  templateUrl: './my-sales.page.html',
})
export class MySalesPageComponent {
  private readonly api = inject(StaffPortalApiService);
  private readonly destroyRef = inject(DestroyRef);

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
          this.loadError.set(extractApiError(err) ?? 'Could not load.');
        },
      });
  }

}
