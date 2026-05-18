import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import {
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  startOfMonth,
  startOfWeek,
} from 'date-fns';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import {
  CalendarComponent,
  CalendarEvent,
} from '../shared/calendar/calendar.component';
import { ContactsApiService } from '../contacts/contacts-api.service';
import {
  Appointment,
  AppointmentsApiService,
} from './appointments-api.service';
import { BookAppointmentModalComponent } from './book-appointment-modal.component';
import { extractApiError } from '@core/services/api-error.util';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
}

@Component({
  selector: 'app-appointments-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    CalendarComponent,
    BookAppointmentModalComponent,
  ],
  templateUrl: './appointments.page.html',
})
export class AppointmentsPageComponent {
  private readonly api = inject(AppointmentsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Calendar's currently-shown month. */
  readonly viewMonth = signal<Date>(new Date());

  /** Currently-clicked day (right panel shows this day's appointments). */
  readonly selectedDay = signal<Date>(new Date());

  /** All appointments overlapping the current viewMonth's visible range. */
  readonly appointments = signal<Appointment[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly contactsById = signal<Record<string, ContactSummary>>({});

  /** Modal state. */
  readonly modalOpen = signal(false);

  /** Events aggregated per local-calendar day for the `<app-calendar>` dots. */
  readonly events = computed<CalendarEvent<Appointment>[]>(() => {
    const map = new Map<string, CalendarEvent<Appointment>>();
    for (const a of this.appointments()) {
      const d = new Date(a.scheduled_at);
      const key = this.dayKey(d);
      const existing = map.get(key);
      if (existing) {
        existing.count += 1;
        existing.items!.push(a);
      } else {
        map.set(key, { date: d, count: 1, items: [a] });
      }
    }
    return [...map.values()];
  });

  /** Appointments for the currently-selected day, sorted by scheduled_at asc. */
  readonly daysAppointments = computed<Appointment[]>(() => {
    const day = this.selectedDay();
    return this.appointments()
      .filter((a) => isSameDay(new Date(a.scheduled_at), day))
      .sort((a, b) =>
        a.scheduled_at < b.scheduled_at ? -1 : a.scheduled_at > b.scheduled_at ? 1 : 0,
      );
  });

  readonly selectedDayLabel = computed(() =>
    format(this.selectedDay(), 'EEEE, d MMMM yyyy'),
  );

  constructor() {
    effect(() => {
      // Re-fetch whenever the visible month changes. The range covers
      // the calendar's spillover days so dots in adjacent-month cells
      // render correctly too.
      const month = this.viewMonth();
      this.reload(month);
    });
  }

  protected onMonthChange(d: Date): void {
    this.viewMonth.set(d);
  }

  protected onDaySelected(d: Date): void {
    this.selectedDay.set(d);
  }

  protected openBook(): void {
    this.modalOpen.set(true);
  }

  protected closeBook(): void {
    this.modalOpen.set(false);
  }

  protected onAppointmentCreated(appt: Appointment): void {
    this.modalOpen.set(false);
    // Jump the calendar + selected day to the newly-booked time.
    const at = new Date(appt.scheduled_at);
    this.viewMonth.set(at);
    this.selectedDay.set(at);
    this.reload(at);
  }

  protected conflictTitleFor = (id: string): string | null => {
    const a = this.appointments().find((x) => x.id === id);
    if (!a) return null;
    const time = format(new Date(a.scheduled_at), 'd MMM, HH:mm');
    return `${a.title} (${time})`;
  };

  protected formatTime(iso: string): string {
    return format(new Date(iso), 'HH:mm');
  }

  protected contactName(id: string): string {
    return this.contactsById()[id]?.full_name ?? 'â€”';
  }

  protected statusClass(status: Appointment['status']): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'cancelled':
        return 'bg-zinc-100 text-zinc-600 ring-zinc-200';
      case 'no_show':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-sky-100 text-sky-700 ring-sky-200';
    }
  }

  private reload(month: Date): void {
    const fromDt = startOfWeek(startOfMonth(month), { weekStartsOn: 1 });
    const toDt = endOfWeek(endOfMonth(month), { weekStartsOn: 1 });
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listRange({
        fromIso: fromDt.toISOString(),
        toIso: toDt.toISOString(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.appointments.set(rows);
          this.loading.set(false);
          this.hydrateContacts(rows);
        },
        error: (err: HttpErrorResponse) => {
          this.appointments.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load appointments.',
          );
        },
      });
  }

  private hydrateContacts(rows: Appointment[]): void {
    const ids = new Set(rows.map((r) => r.contact_id));
    const cache = this.contactsById();
    const missing = [...ids].filter((id) => !cache[id]);
    if (missing.length === 0) return;
    forkJoin(
      missing.map((id) =>
        this.contactsApi.get(id).pipe(catchError(() => of(null))),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((current) => {
          const next = { ...current };
          for (const c of results) {
            if (c) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
              };
            }
          }
          return next;
        });
      });
  }

  private dayKey(d: Date): string {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

}
