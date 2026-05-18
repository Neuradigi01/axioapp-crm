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
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ContactsApiService } from '../contacts/contacts-api.service';
import { InrPipe } from '../shared/pipes/inr.pipe';
import {
  QuickRegisterResponse,
  WalkIn,
  WalkInStatus,
  WalkInsApiService,
} from './walk-ins-api.service';
import { RegisterWalkinModalComponent } from './register-walkin-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
}

type StatusFilter = 'all' | WalkInStatus;

const FILTER_CHIPS: ReadonlyArray<{ id: StatusFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'browsing', label: 'Browsing' },
  { id: 'interested', label: 'Interested' },
  { id: 'follow_up', label: 'Follow-up' },
  { id: 'converted', label: 'Converted' },
  { id: 'left', label: 'Left' },
];

@Component({
  selector: 'app-walk-ins-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, InrPipe, RegisterWalkinModalComponent],
  templateUrl: './walk-ins.page.html',
})
export class WalkInsPageComponent {
  protected readonly initials = initials;
  private readonly api = inject(WalkInsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly all = signal<WalkIn[]>([]);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly statusFilter = signal<StatusFilter>('all');
  readonly chips = FILTER_CHIPS;

  readonly contactsById = signal<Record<string, ContactSummary>>({});
  readonly modalOpen = signal(false);

  /** Items filtered by the current chip, sorted by time_in desc. */
  readonly visible = computed<WalkIn[]>(() => {
    const filter = this.statusFilter();
    const rows = filter === 'all'
      ? this.all()
      : this.all().filter((w) => w.status === filter);
    return [...rows].sort((a, b) =>
      a.time_in < b.time_in ? 1 : a.time_in > b.time_in ? -1 : 0,
    );
  });

  // --- KPI cards (computed from `all`) ---

  readonly todayCount = computed(() =>
    this.all().filter((w) => this.isToday(w.time_in)).length,
  );
  readonly convertedTodayCount = computed(() =>
    this.all().filter(
      (w) => w.status === 'converted' && this.isToday(w.updated_at),
    ).length,
  );
  /** Combined "warm leads" count â€” interested + follow_up across all loaded rows. */
  readonly interestedOrFollowUpCount = computed(
    () =>
      this.all().filter(
        (w) => w.status === 'interested' || w.status === 'follow_up',
      ).length,
  );
  readonly conversionRate = computed(() => {
    const today = this.todayCount();
    if (today === 0) return null;
    const converted = this.convertedTodayCount();
    return Math.round((converted / today) * 100);
  });
  /** Average visit duration in minutes, across all checked-out walk-ins. */
  readonly avgVisitDuration = computed<number | null>(() => {
    const completed = this.all()
      .map((w) => (w.duration_min !== null ? Number(w.duration_min) : null))
      .filter((n): n is number => n !== null && Number.isFinite(n));
    if (completed.length === 0) return null;
    const total = completed.reduce((a, b) => a + b, 0);
    return Math.round(total / completed.length);
  });

  constructor() {
    this.reload();
    effect(() => {
      // Fetch missing contact summaries whenever the visible list changes.
      const ids = new Set(this.all().map((w) => w.contact_id));
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });
  }

  protected setFilter(f: StatusFilter): void {
    this.statusFilter.set(f);
  }

  protected openRegister(): void {
    this.modalOpen.set(true);
  }

  protected closeRegister(): void {
    this.modalOpen.set(false);
  }

  protected onRegistered(_event: QuickRegisterResponse): void {
    this.modalOpen.set(false);
    this.reload();
  }

  protected onCheckout(walkIn: WalkIn): void {
    // Optimistic: stamp time_out locally to a near-now ISO so the
    // duration column populates immediately. Replaced by server value.
    const optimisticNow = new Date().toISOString();
    const before = this.all();
    this.all.update((rows) =>
      rows.map((w) =>
        w.id === walkIn.id ? { ...w, time_out: optimisticNow } : w,
      ),
    );
    this.api
      .checkout(walkIn.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.all.update((rows) =>
            rows.map((w) => (w.id === updated.id ? updated : w)),
          );
        },
        error: (err: HttpErrorResponse) => {
          this.all.set(before);
          this.loadError.set(
            extractApiError(err) ?? 'Could not check out walk-in.',
          );
        },
      });
  }

  protected statusClass(status: WalkInStatus): string {
    switch (status) {
      case 'browsing':
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
      case 'interested':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'follow_up':
        return 'bg-sky-100 text-sky-700 ring-sky-200';
      case 'converted':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'left':
        return 'bg-red-100 text-red-700 ring-red-200';
    }
  }


  protected contactFor(id: string): ContactSummary | null {
    return this.contactsById()[id] ?? null;
  }

  protected formatTime(iso: string | null): string {
    if (iso === null) return 'â€”';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'â€”';
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected formatDate(iso: string | null): string {
    if (iso === null) return 'â€”';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'â€”';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  /** No users-list API yet â€” show a short id snippet, or "â€”" if unassigned. */
  protected assignedToLabel(id: string | null): string {
    if (id === null) return 'â€”';
    return id.slice(0, 8);
  }

  protected formatDuration(min: string | null): string {
    if (min === null) return 'â€”';
    const n = Number(min);
    if (!Number.isFinite(n)) return 'â€”';
    if (n < 1) return `${Math.round(n * 60)}s`;
    if (n < 60) return `${Math.round(n)} min`;
    const hours = Math.floor(n / 60);
    const rem = Math.round(n % 60);
    return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`;
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ size: 100 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.all.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.all.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load walk-ins.',
          );
        },
      });
  }

  private fetchContacts(ids: string[]): void {
    forkJoin(
      ids.map((id) =>
        this.contactsApi.get(id).pipe(catchError(() => of(null))),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of results) {
            if (c) next[c.id] = { id: c.id, full_name: c.full_name, phone: c.phone };
          }
          return next;
        });
      });
  }

  private isToday(iso: string): boolean {
    const d = new Date(iso);
    const now = new Date();
    return (
      d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate()
    );
  }

}
