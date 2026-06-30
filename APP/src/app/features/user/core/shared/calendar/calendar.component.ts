import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek,
  subMonths,
} from 'date-fns';

/**
 * Generic month-grid calendar. Renders a 7×6 grid of day cells (the
 * spillover days from neighbouring months are rendered greyed-out so
 * the grid stays a stable shape — no rows jumping around as months
 * change length).
 *
 * Inputs are intentionally domain-free — the caller passes an array
 * of `CalendarEvent` objects (date + count + optional payload) and the
 * calendar draws dot indicators per day. Click a day → emits
 * `daySelected(date)`. Click chevrons → emits `viewMonthChange(date)`.
 *
 * No appointment-, contact-, or lead-specific logic lives here. Same
 * component will back walk-in scheduling and field-ops calendars in
 * later phases.
 */
export interface CalendarEvent<T = unknown> {
  date: Date;
  count: number;
  items?: T[];
}

@Component({
  selector: 'app-calendar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './calendar.component.html',
})
export class CalendarComponent {
  readonly viewMonth = input.required<Date>();
  readonly events = input<CalendarEvent[]>([]);
  readonly selectedDay = input<Date | null>(null);

  readonly viewMonthChange = output<Date>();
  readonly daySelected = output<Date>();

  readonly weekdayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  readonly monthLabel = computed(() => format(this.viewMonth(), 'MMMM yyyy'));

  /** Quick lookup: ISO yyyy-mm-dd → count of events on that day. */
  readonly eventsByDayKey = computed<Map<string, number>>(() => {
    const out = new Map<string, number>();
    for (const ev of this.events()) {
      const key = this._key(ev.date);
      out.set(key, (out.get(key) ?? 0) + ev.count);
    }
    return out;
  });

  /** The 42 (7×6) cells covering the month, padded with prev/next-month spillover. */
  readonly days = computed<Date[]>(() => {
    const month = this.viewMonth();
    const start = startOfWeek(startOfMonth(month), { weekStartsOn: 1 });
    const end = endOfWeek(endOfMonth(month), { weekStartsOn: 1 });
    return eachDayOfInterval({ start, end });
  });

  protected previousMonth(): void {
    this.viewMonthChange.emit(subMonths(this.viewMonth(), 1));
  }

  protected nextMonth(): void {
    this.viewMonthChange.emit(addMonths(this.viewMonth(), 1));
  }

  protected goToToday(): void {
    this.viewMonthChange.emit(new Date());
    this.daySelected.emit(new Date());
  }

  protected onDayClick(day: Date): void {
    this.daySelected.emit(day);
  }

  protected dayNumber(d: Date): number {
    return d.getDate();
  }

  protected isInViewMonth(d: Date): boolean {
    return isSameMonth(d, this.viewMonth());
  }

  protected isTodayCell(d: Date): boolean {
    return isToday(d);
  }

  protected isSelected(d: Date): boolean {
    const sel = this.selectedDay();
    return sel !== null && isSameDay(d, sel);
  }

  protected eventCount(d: Date): number {
    return this.eventsByDayKey().get(this._key(d)) ?? 0;
  }

  protected dotsToRender(count: number): readonly number[] {
    // Cap at 3 dots — a "+N" badge handles overflow.
    const max = 3;
    return Array.from({ length: Math.min(count, max) }, (_, i) => i);
  }

  protected overflowCount(count: number): number {
    return count > 3 ? count - 3 : 0;
  }

  private _key(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
}
