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
import { ActivatedRoute, Router } from '@angular/router';
import { NgTemplateOutlet } from '@angular/common';
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
 * Staff Dashboard — admin-facing tab host. The 5 real tabs read from
 * `loadWithPerformance()` (one /staff + N /staff/{id}/performance calls
 * in parallel) and share the result via input bindings to keep child
 * tabs cheap to switch between. The 3 placeholder tabs are stubs until
 * Phase 4.4 / 4.10 / 5.6 ship.
 *
 * KPI header mirrors the Vercel reference layout — Present-today,
 * total staff, total revenue, avg target progress, today's revenue.
 * Each KPI is `undefined` while loading and `null` when its call
 * failed, so the header never passes off a failure as a real "0".
 *
 * The active tab lives in `?tab=` so a reload or shared link keeps it.
 */
@Component({
  selector: 'app-staff-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
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
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly rows = signal<StaffWithPerformance[]>([]);
  /** First load only — replaces the tab body with a loader. */
  protected readonly loading = signal(false);
  /** Refresh after the first load — tabs stay mounted (so pickers /
   *  open editors keep their state) and only the button spins. */
  protected readonly refreshing = signal(false);
  protected readonly loadError = signal<string | null>(null);
  private hasLoaded = false;

  /** Present-today headcount from `/staff/present-today`. Independent
   * of the roster so a bad attendance query never blanks the page.
   * `undefined` = loading, `null` = failed. */
  private readonly presentTodayCount = signal<number | null | undefined>(undefined);

  /** Sums of paid-invoice `Invoice.total` from `/staff/revenue-totals`.
   * Same independent pattern — a broken billing query shouldn't wipe
   * the roster. `undefined` = loading, `null` = failed. */
  private readonly revenue = signal<{ total: number; today: number } | null | undefined>(undefined);

  protected readonly activeTab = signal<StaffTabId>('overview');

  // Stock Updates and Store Marketing tabs are hidden — the underlying
  // modules aren't built yet (were referenced by the deleted master-
  // prompt Phase 4.4 / 5.6). Leave the tab-id enum in place so the
  // template's @switch keeps compiling until the modules ship; then
  // just re-add the entries here.
  protected readonly tabs: ReadonlyArray<{ id: StaffTabId; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'leaderboard', label: 'Leaderboard' },
    { id: 'targets', label: 'Targets & Commission' },
    { id: 'attendance', label: 'Attendance' },
    { id: 'activity', label: 'Activity Log' },
    { id: 'field-ops', label: 'Field Operations' },
  ];

  // --- KPI header — `undefined` = loading, `null` = unavailable ---

  /** Roster-derived KPIs are unknown until the first load lands, and
   *  unavailable if it failed with nothing on screen. */
  private readonly rosterState = computed<'loading' | 'error' | 'ok'>(() => {
    if (this.loading()) return 'loading';
    if (this.loadError() && this.rows().length === 0) return 'error';
    return 'ok';
  });

  protected readonly totalStaff = computed<number | null | undefined>(() => {
    const st = this.rosterState();
    return st === 'loading' ? undefined : st === 'error' ? null : this.rows().length;
  });

  protected readonly presentToday = computed(() => this.presentTodayCount());

  protected readonly totalRevenue = computed(() => {
    const r = this.revenue();
    return r === undefined || r === null ? r : r.total;
  });

  protected readonly todaysRevenue = computed(() => {
    const r = this.revenue();
    return r === undefined || r === null ? r : r.today;
  });

  /** Average target progress across staff who actually have a target —
   *  people without a profile (`null`) would otherwise count as 0%
   *  and drag the average down. `null` when nobody has a target. */
  protected readonly avgTargetProgressPct = computed<number | null | undefined>(() => {
    const st = this.rosterState();
    if (st !== 'ok') return st === 'loading' ? undefined : null;
    const pcts = this.rows()
      .map((r) => r.performance.target_progress_pct)
      .filter((p): p is number => p !== null);
    if (pcts.length === 0) return null;
    return Math.round(pcts.reduce((acc, p) => acc + p, 0) / pcts.length);
  });

  constructor() {
    const fromUrl = this.route.snapshot.queryParamMap.get('tab');
    if (fromUrl && this.tabs.some((t) => t.id === fromUrl)) {
      this.activeTab.set(fromUrl as StaffTabId);
    }
    this.reload();
  }

  protected reload(): void {
    if (this.loading() || this.refreshing()) return;
    if (this.hasLoaded) this.refreshing.set(true);
    else this.loading.set(true);
    this.loadError.set(null);
    this.api
      .loadWithPerformance()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.rows.set(rows);
          this.hasLoaded = true;
          this.loading.set(false);
          this.refreshing.set(false);
        },
        error: (err: HttpErrorResponse) => {
          // A failed refresh keeps the roster already on screen; only a
          // failed first load leaves the page empty.
          if (!this.hasLoaded) this.rows.set([]);
          this.loading.set(false);
          this.refreshing.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load staff.');
        },
      });
    // Present-today is an independent call — errors here don't blank
    // the roster; the KPI shows "—" instead of a fake 0.
    this.api
      .presentToday()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => this.presentTodayCount.set(r.count),
        error: () => this.presentTodayCount.set(null),
      });
    // Revenue KPIs — same independent-load pattern; a billing outage
    // shouldn't blank the whole staff page.
    this.api
      .revenueTotals()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => this.revenue.set({ total: r.total, today: r.today }),
        error: () => this.revenue.set(null),
      });
  }

  protected setTab(tab: StaffTabId): void {
    this.activeTab.set(tab);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tab: tab === 'overview' ? null : tab },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
