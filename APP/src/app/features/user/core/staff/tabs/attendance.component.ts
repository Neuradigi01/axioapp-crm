import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';

import { CalendarComponent } from '../../shared/calendar/calendar.component';
import { CalendarEvent } from '../../shared/calendar/calendar.component';
import { extractApiError } from '@core/services/api-error.util';
import {
  StaffApiService,
  AttendanceOut,
  StaffWithPerformance,
} from '../staff-api.service';

/**
 * Attendance tab â€” picks one staff member (the first row by default),
 * lets the admin browse their month-grid via the shared calendar, and
 * lists the raw clock-in/out rows for that month below.
 *
 * The calendar dots are seeded from each `AttendanceOut.clock_in_at`
 * (so days with multiple sessions show a higher count). Switching the
 * staff dropdown reloads the rows; navigating months also reloads
 * (server filters by `from` / `to`).
 */
@Component({
  selector: 'app-staff-attendance-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CalendarComponent],
  templateUrl: './attendance.component.html',
})
export class StaffAttendanceTabComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly rows = input.required<StaffWithPerformance[]>();

  protected readonly selectedUserId = signal<string | null>(null);
  protected readonly viewMonth = signal<Date>(new Date());
  protected readonly attendance = signal<AttendanceOut[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly selectedStaff = computed(() => {
    const id = this.selectedUserId();
    return this.rows().find((r) => r.staff.id === id) ?? null;
  });

  protected readonly events = computed<CalendarEvent[]>(() =>
    this.attendance().map((a) => ({
      date: new Date(a.clock_in_at),
      count: 1,
    })),
  );

  protected readonly totalHours = computed(() => {
    let total = 0;
    for (const a of this.attendance()) {
      total += Number(a.hours ?? 0);
    }
    return total.toFixed(2);
  });

  constructor() {
    // Default-pick the first staff once rows arrive.
    effect(() => {
      const list = this.rows();
      if (list.length > 0 && this.selectedUserId() === null) {
        this.selectedUserId.set(list[0].staff.id);
      }
    });
    // Reload attendance whenever staff or month changes.
    effect(() => {
      const id = this.selectedUserId();
      const month = this.viewMonth();
      if (id) this.fetch(id, month);
    });
  }

  protected pickStaff(event: Event): void {
    const id = (event.target as HTMLSelectElement).value;
    this.selectedUserId.set(id || null);
  }

  protected onViewMonthChange(d: Date): void {
    this.viewMonth.set(d);
  }

  protected onDaySelected(_d: Date): void {
    // Reserved for future drilldown â€” silenced for now.
  }

  protected formatTime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  protected formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString();
  }

  private fetch(userId: string, month: Date): void {
    this.loading.set(true);
    this.loadError.set(null);
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    const iso = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    this.api
      .attendance(userId, iso(first), iso(last))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.attendance.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.attendance.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load attendance.',
          );
        },
      });
  }

}
