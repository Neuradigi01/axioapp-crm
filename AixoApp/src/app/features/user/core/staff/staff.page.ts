import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { InrPipe } from '../shared/pipes/inr.pipe';
import { StaffApiService, StaffWithPerformance } from './staff-api.service';
import { StaffOverviewTabComponent } from './tabs/overview.component';
import { StaffLeaderboardTabComponent } from './tabs/leaderboard.component';
import { StaffTargetsTabComponent } from './tabs/targets.component';
import { StaffAttendanceTabComponent } from './tabs/attendance.component';
import { StaffActivityTabComponent } from './tabs/activity.component';
import { StaffFieldOpsTabComponent } from './tabs/field-ops.component';
import { StaffPlaceholderTabComponent } from './tabs/placeholder.component';
import { extractApiError } from '@core/services/api-error.util';

export type StaffTabId =
  | 'overview'
  | 'leaderboard'
  | 'targets'
  | 'attendance'
  | 'activity'
  | 'field-ops'
  | 'stock-updates'
  | 'store-marketing';

/**
 * Staff Dashboard â€” admin-facing tab host. The 5 real tabs read from
 * `loadWithPerformance()` (one /staff + N /staff/{id}/performance calls
 * in parallel) and share the result via input bindings to keep child
 * tabs cheap to switch between. The 3 placeholder tabs are stubs until
 * Phase 4.4 / 4.10 / 5.6 ship.
 *
 * KPI header mirrors the Vercel reference layout â€” Present-today,
 * total staff, total revenue (placeholder zero until invoices land),
 * avg conversion %, today's revenue (also zero today).
 */
@Component({
  selector: 'app-staff-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    InrPipe,
    StaffOverviewTabComponent,
    StaffLeaderboardTabComponent,
    StaffTargetsTabComponent,
    StaffAttendanceTabComponent,
    StaffActivityTabComponent,
    StaffFieldOpsTabComponent,
    StaffPlaceholderTabComponent,
  ],
  templateUrl: './staff.page.html',
})
export class StaffPageComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rows = signal<StaffWithPerformance[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly activeTab = signal<StaffTabId>('overview');

  protected readonly tabs: ReadonlyArray<{ id: StaffTabId; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'leaderboard', label: 'Leaderboard' },
    { id: 'targets', label: 'Targets & Commission' },
    { id: 'attendance', label: 'Attendance' },
    { id: 'activity', label: 'Activity Log' },
    { id: 'field-ops', label: 'Field Operations' },
    { id: 'stock-updates', label: 'Stock Updates' },
    { id: 'store-marketing', label: 'Store Marketing' },
  ];

  // --- KPI header (computed from the joined rows) ---

  protected readonly totalStaff = computed(() => this.rows().length);

  protected readonly presentToday = computed(() => {
    // Present-today isn't returned by the list endpoint; we leave the
    // numerator at 0 here and fill it in once the staff-portal clock-in
    // ledger is queryable from the admin side (Phase 3.6).
    return 0;
  });

  protected readonly totalRevenue = computed(() => {
    // Sum of leaderboard.sales â€” sales placeholder is 0 today.
    return this.rows().reduce((acc, r) => acc + Number(r.performance.sales || 0), 0);
  });

  protected readonly avgConversionPct = computed(() => {
    const rs = this.rows();
    if (rs.length === 0) return 0;
    const total = rs.reduce((acc, r) => acc + (r.performance.target_progress_pct ?? 0), 0);
    return Math.round(total / rs.length);
  });

  protected readonly todaysRevenue = computed(() => {
    // Same Phase-5 placeholder as totalRevenue.
    return 0;
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .loadWithPerformance()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.rows.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.rows.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load staff.');
        },
      });
  }

  protected setTab(tab: StaffTabId): void {
    this.activeTab.set(tab);
  }
}
