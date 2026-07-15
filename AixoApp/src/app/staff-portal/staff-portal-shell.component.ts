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
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { StaffAttendance, StaffPortalApiService } from './staff-portal-api.service';
import { StaffSessionService } from './staff-session.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Tablet shell â€” minimal, no admin sidebar. Top bar carries:
 *
 *   left   : "FurnitureCRM" wordmark + greeting (full_name)
 *   centre : tab nav (Dashboard Â· Attendance Â· Activity Â· Sales Â· Stock Â· Field)
 *   right  : clock-in/out widget + logout
 *
 * Clock-in/out lives on the shell (not on My Attendance) per the
 * step spec: "Clock In/Out widget visible globally on the portal
 * shell (top bar)". A single shared `openSession` signal is kept here
 * so the rest of the portal can read/derive from it.
 */
@Component({
  selector: 'app-staff-portal-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './staff-portal-shell.component.html',
})
export class StaffPortalShellComponent {
  private readonly api = inject(StaffPortalApiService);
  private readonly session = inject(StaffSessionService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly fullName = this.session.fullName;

  protected readonly clockingIn = signal(false);
  protected readonly clockingOut = signal(false);
  protected readonly clockError = signal<string | null>(null);
  protected readonly openSession = signal<StaffAttendance | null>(null);

  protected readonly tabs: ReadonlyArray<{ path: string; label: string }> = [
    { path: 'dashboard', label: 'Dashboard' },
    { path: 'attendance', label: 'Attendance' },
    { path: 'activity', label: 'Activity' },
    { path: 'sales', label: 'Sales' },
    { path: 'stock', label: 'Stock' },
    { path: 'field', label: 'Field' },
  ];

  protected readonly clockButtonLabel = computed(() =>
    this.openSession() ? 'Clock Out' : 'Clock In',
  );

  constructor() {
    this.refreshOpenSession();
  }

  protected toggleClock(): void {
    this.clockError.set(null);
    if (this.openSession()) {
      this.clockingOut.set(true);
      this.api
        .clockOut()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.clockingOut.set(false);
            this.openSession.set(null);
          },
          error: (err: HttpErrorResponse) => {
            this.clockingOut.set(false);
            this.clockError.set(extractApiError(err) ?? 'Could not clock out.');
          },
        });
    } else {
      this.clockingIn.set(true);
      this.api
        .clockIn()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (row) => {
            this.clockingIn.set(false);
            this.openSession.set(row);
          },
          error: (err: HttpErrorResponse) => {
            this.clockingIn.set(false);
            this.clockError.set(extractApiError(err) ?? 'Could not clock in.');
          },
        });
    }
  }

  protected logout(): void {
    this.session.clear();
    this.router.navigate(['/staff-portal/login']);
  }

  private refreshOpenSession(): void {
    this.api
      .attendance()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const open = rows.find((r) => r.clock_out_at === null) ?? null;
          this.openSession.set(open);
        },
        error: () => {
          // Non-fatal â€” shell still usable without the badge.
        },
      });
  }
}
