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
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import {
  Appointment,
  AppointmentsApiService,
} from '../../../core/appointments/appointments-api.service';
import { ContactsApiService } from '../../../core/contacts/contacts-api.service';
import {
  FieldOpsApiService,
  FieldVisit,
} from './field-ops-api.service';
import { ScheduleVisitModalComponent } from './schedule-visit-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { purposeBadgeClass } from '@core/services/badge.util';

type Filter = 'today' | 'upcoming' | 'completed';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
}

@Component({
  selector: 'app-field-ops-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, ScheduleVisitModalComponent],
  templateUrl: './field-ops.page.html',
})
export class FieldOpsPageComponent {
  protected readonly purposeBadgeClass = purposeBadgeClass;
  private readonly api = inject(FieldOpsApiService);
  private readonly appointmentsApi = inject(AppointmentsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly visits = signal<FieldVisit[]>([]);
  protected readonly appointmentsById = signal<Record<string, Appointment>>({});
  protected readonly contactsById = signal<Record<string, ContactSummary>>({});

  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly filter = signal<Filter>('today');
  protected readonly modalOpen = signal(false);
  protected readonly submitting = signal(false);

  protected readonly filters: { id: Filter; label: string }[] = [
    { id: 'today', label: 'Today' },
    { id: 'upcoming', label: 'Upcoming' },
    { id: 'completed', label: 'Completed' },
  ];

  /** Filtered visits joined with appointment data, ordered by scheduled time. */
  protected readonly view = computed(() => {
    const all = this.visits();
    const apptIdx = this.appointmentsById();
    const filt = this.filter();
    const todayKey = this.dayKey(new Date());

    const enriched = all.map((v) => ({
      visit: v,
      appt: apptIdx[v.appointment_id] ?? null,
    }));

    const filtered = enriched.filter(({ visit, appt }) => {
      if (filt === 'completed') return visit.completed_at !== null;
      if (visit.completed_at !== null) return false;
      if (!appt) return filt === 'upcoming';
      const apptKey = this.dayKey(new Date(appt.scheduled_at));
      if (filt === 'today') return apptKey === todayKey;
      // upcoming: future days only (today's open ones live in `today`)
      return new Date(appt.scheduled_at).getTime() > Date.now()
        && apptKey !== todayKey;
    });

    return filtered.sort((a, b) => {
      const aMs = a.appt ? new Date(a.appt.scheduled_at).getTime() : 0;
      const bMs = b.appt ? new Date(b.appt.scheduled_at).getTime() : 0;
      return aMs - bMs;
    });
  });

  protected readonly counts = computed(() => {
    const apptIdx = this.appointmentsById();
    const todayKey = this.dayKey(new Date());
    let today = 0;
    let upcoming = 0;
    let completed = 0;
    for (const v of this.visits()) {
      if (v.completed_at) {
        completed += 1;
        continue;
      }
      const appt = apptIdx[v.appointment_id];
      if (!appt) {
        upcoming += 1;
        continue;
      }
      const apptKey = this.dayKey(new Date(appt.scheduled_at));
      if (apptKey === todayKey) today += 1;
      else if (new Date(appt.scheduled_at).getTime() > Date.now())
        upcoming += 1;
    }
    return { today, upcoming, completed };
  });

  constructor() {
    this.reload();

    // Fetch appointment + contact data for visits we haven't joined yet.
    effect(() => {
      const visits = this.visits();
      const apptIds = new Set(visits.map((v) => v.appointment_id));
      const apptCache = this.appointmentsById();
      const missingAppts = [...apptIds].filter((id) => !apptCache[id]);
      if (missingAppts.length > 0) this.fetchAppointments(missingAppts);
    });

    effect(() => {
      const apptIdx = this.appointmentsById();
      const contactIds = new Set(
        Object.values(apptIdx).map((a) => a.contact_id),
      );
      const cache = this.contactsById();
      const missing = [...contactIds].filter((id) => !cache[id]);
      if (missing.length > 0) this.fetchContacts(missing);
    });
  }

  protected setFilter(f: Filter): void {
    this.filter.set(f);
  }

  protected openSchedule(): void {
    this.modalOpen.set(true);
  }

  protected closeModal(): void {
    this.modalOpen.set(false);
    this.submitting.set(false);
  }

  protected onCreated(): void {
    this.closeModal();
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.visits.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.visits.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load field visits.',
          );
        },
      });
  }

  protected formatTime(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  }

  protected formatDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }


  protected contactName(id: string): string {
    return this.contactsById()[id]?.full_name ?? 'Unknown';
  }

  protected contactPhone(id: string): string | null {
    return this.contactsById()[id]?.phone ?? null;
  }

  private dayKey(d: Date): string {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  private fetchAppointments(ids: string[]): void {
    forkJoin(
      ids.map((id) =>
        this.appointmentsApi.get(id).pipe(catchError(() => of(null))),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((rows) => {
        this.appointmentsById.update((cache) => {
          const next = { ...cache };
          for (const a of rows) if (a) next[a.id] = a;
          return next;
        });
      });
  }

  private fetchContacts(ids: string[]): void {
    forkJoin(
      ids.map((id) =>
        this.contactsApi.get(id).pipe(catchError(() => of(null))),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((rows) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of rows) {
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

}
