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
import { NgTemplateOutlet } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';

import { CalendarComponent } from '../../shared/calendar/calendar.component';
import { CalendarEvent } from '../../shared/calendar/calendar.component';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import { extractApiError } from '@core/services/api-error.util';
import { StaffApiService, AttendanceOut, StaffWithPerformance } from '../staff-api.service';

/** One calendar day of attendance for the selected staff member. */
interface AttendanceDay {
  /** Local-date key `YYYY-MM-DD`. */
  key: string;
  date: Date;
  /** Sessions in chronological order (earliest clock-in first). */
  sessions: AttendanceOut[];
  firstIn: string;
  /** Latest clock-out, or `null` while a session is still open. */
  lastOut: string | null;
  /** Sum of closed sessions, in minutes. */
  totalMinutes: number;
  hasOpen: boolean;
}

/** Local-date key — groups by the viewer's day, not the server's UTC `date`. */
function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * Attendance tab — picks one staff member (the first row by default),
 * lets the admin browse their month-grid via the shared calendar, and
 * lists that month's clock-in/out sessions grouped by day.
 *
 * Each day row shows first in → last out, session count and total
 * time, and expands to the individual sessions. Clicking a day on the
 * calendar narrows the panel to just that day (click it again, or
 * "Whole month", to go back). Switching staff or month reloads the
 * rows (server filters by `from` / `to`) and clears the selected day.
 */
@Component({
  selector: 'app-staff-attendance-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CalendarComponent, LucideAngularModule, MobileSelectComponent, NgTemplateOutlet],
  templateUrl: './attendance.component.html',
})
export class StaffAttendanceTabComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly rows = input.required<StaffWithPerformance[]>();

  protected readonly selectedUserId = signal<string | null>(null);
  protected readonly viewMonth = signal<Date>(new Date());
  protected readonly selectedDay = signal<Date | null>(null);
  protected readonly expandedKeys = signal<ReadonlySet<string>>(new Set());
  protected readonly attendance = signal<AttendanceOut[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly selectedStaff = computed(() => {
    const id = this.selectedUserId();
    return this.rows().find((r) => r.staff.id === id) ?? null;
  });

  protected readonly staffOptions = computed<MobileSelectOption[]>(() =>
    this.rows().map((r) => ({ value: r.staff.id, label: r.staff.full_name })),
  );

  protected readonly events = computed<CalendarEvent[]>(() =>
    this.days().map((d) => ({ date: d.date, count: d.sessions.length })),
  );

  /** Month's sessions grouped by local day, newest day first. */
  protected readonly days = computed<AttendanceDay[]>(() => {
    const byKey = new Map<string, AttendanceOut[]>();
    for (const a of this.attendance()) {
      const key = dayKey(new Date(a.clock_in_at));
      const list = byKey.get(key);
      if (list) list.push(a);
      else byKey.set(key, [a]);
    }
    const days: AttendanceDay[] = [];
    for (const [key, list] of byKey) {
      const sessions = [...list].sort((x, y) => x.clock_in_at.localeCompare(y.clock_in_at));
      const hasOpen = sessions.some((s) => s.clock_out_at === null);
      const closedOuts = sessions
        .map((s) => s.clock_out_at)
        .filter((v): v is string => v !== null)
        .sort();
      days.push({
        key,
        date: new Date(sessions[0].clock_in_at),
        sessions,
        firstIn: sessions[0].clock_in_at,
        lastOut: hasOpen ? null : closedOuts[closedOuts.length - 1],
        totalMinutes: sessions.reduce((sum, s) => sum + this.sessionMinutes(s), 0),
        hasOpen,
      });
    }
    return days.sort((a, b) => b.key.localeCompare(a.key));
  });

  /** The selected calendar day's group; `undefined` when no day is selected. */
  protected readonly selectedDayGroup = computed<AttendanceDay | null | undefined>(() => {
    const sel = this.selectedDay();
    if (!sel) return undefined;
    return this.days().find((d) => d.key === dayKey(sel)) ?? null;
  });

  protected readonly monthTotalMinutes = computed(() =>
    this.days().reduce((sum, d) => sum + d.totalMinutes, 0),
  );

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

  protected pickStaff(value: string): void {
    this.selectedUserId.set(value || null);
    this.clearSelection();
  }

  protected onViewMonthChange(d: Date): void {
    this.viewMonth.set(d);
    this.clearSelection();
  }

  /** Toggle the day drill-down; clicking the selected day again clears it. */
  protected onDaySelected(d: Date): void {
    const current = this.selectedDay();
    this.selectedDay.set(current && dayKey(current) === dayKey(d) ? null : d);
  }

  protected showWholeMonth(): void {
    this.selectedDay.set(null);
  }

  protected toggleExpanded(key: string): void {
    const next = new Set(this.expandedKeys());
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this.expandedKeys.set(next);
  }

  protected formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  protected formatDayShort(d: Date): string {
    return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
  }

  protected formatDayLong(d: Date): string {
    return d.toLocaleDateString([], {
      weekday: 'long',
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }

  /** `7h 40m` / `45m` / `0m`. */
  protected formatDuration(minutes: number): string {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  protected sessionMinutes(s: AttendanceOut): number {
    return s.hours === null ? 0 : Math.round(Number(s.hours) * 60);
  }

  private clearSelection(): void {
    this.selectedDay.set(null);
    this.expandedKeys.set(new Set());
  }

  private fetch(userId: string, month: Date): void {
    this.loading.set(true);
    this.loadError.set(null);
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    this.api
      .attendance(userId, dayKey(first), dayKey(last))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.attendance.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.attendance.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load attendance.');
        },
      });
  }
}
