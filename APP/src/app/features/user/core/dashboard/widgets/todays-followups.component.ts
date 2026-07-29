import { CommonModule } from '@angular/common';
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
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, interval } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';

import { RescheduleInlineComponent } from './reschedule-inline.component';
import {
  FollowupBucket,
  FollowupItem,
  FollowupPriority,
  FollowupType,
  FollowupsResponse,
  TodaysFollowupsApiService,
} from './todays-followups-api.service';

/**
 * Dashboard widget — "Today's Follow-ups". Renders the caller's
 * follow-up tasks (bucketed) with inline Complete / Reschedule /
 * Mark-as-missed / Open actions. Auto-polls every 60 seconds.
 *
 * Scope is decided server-side (`users.read` → org view, otherwise
 * personal). The widget's chip counts + list body are driven by the
 * same `GET /dashboard/followups` payload so they always agree.
 */
type BucketChip = {
  readonly key: FollowupBucket;
  readonly label: string;
  readonly countKey:
    | 'today_total'
    | 'pending_today'
    | 'completed_today'
    | 'overdue'
    | 'missed_last_7d';
};

const BUCKET_CHIPS: readonly BucketChip[] = [
  { key: 'today', label: 'Today', countKey: 'today_total' },
  { key: 'pending', label: 'Pending', countKey: 'pending_today' },
  { key: 'completed_today', label: 'Completed', countKey: 'completed_today' },
  { key: 'overdue', label: 'Overdue', countKey: 'overdue' },
  { key: 'missed', label: 'Missed (7d)', countKey: 'missed_last_7d' },
];

const FOLLOWUP_TYPE_LABELS: Record<FollowupType, { label: string; icon: string }> = {
  call: { label: 'Call', icon: 'phone' },
  whatsapp: { label: 'WhatsApp', icon: 'message-circle' },
  email: { label: 'Email', icon: 'mail' },
  document: { label: 'Document', icon: 'file-text' },
  meeting: { label: 'Meeting', icon: 'calendar-clock' },
  other: { label: 'Other', icon: 'circle-dot' },
};

const PRIORITY_LABELS: Record<FollowupPriority, { label: string; dot: string; text: string }> = {
  high: { label: 'High', dot: 'bg-red-500', text: 'text-red-400' },
  med: { label: 'Med', dot: 'bg-amber-500', text: 'text-amber-700' },
  low: { label: 'Low', dot: 'bg-sky-500', text: 'text-sky-700' },
};

@Component({
  selector: 'app-todays-followups',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule, RouterLink, RescheduleInlineComponent],
  templateUrl: './todays-followups.component.html',
})
export class TodaysFollowupsComponent {
  private readonly api = inject(TodaysFollowupsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly buckets = BUCKET_CHIPS;

  protected readonly bucket = signal<FollowupBucket>('today');
  protected readonly response = signal<FollowupsResponse | null>(null);
  protected readonly loading = signal(true);
  protected readonly refreshing = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly searchTerm = signal('');
  protected readonly showFilters = signal(false);
  protected readonly filterType = signal<FollowupType | ''>('');
  protected readonly filterPriority = signal<FollowupPriority | ''>('');

  /** Row id currently in reschedule-picker mode. */
  protected readonly reschedulingId = signal<string | null>(null);
  /** Row ids optimistically flipped to `done` so we can revert on error. */
  protected readonly optimisticallyDone = signal<ReadonlySet<string>>(new Set());
  /** Row ids optimistically flipped to `missed`. Same revert-on-error
   *  contract as `optimisticallyDone`. */
  protected readonly optimisticallyMissed = signal<ReadonlySet<string>>(new Set());

  protected readonly items = computed<FollowupItem[]>(() => {
    const resp = this.response();
    if (!resp) return [];
    const done = this.optimisticallyDone();
    const missed = this.optimisticallyMissed();
    return resp.items.map((it) => {
      if (done.has(it.id)) return { ...it, status: 'done' as const };
      if (missed.has(it.id)) return { ...it, status: 'missed' as const };
      return it;
    });
  });

  protected readonly counts = computed(() => this.response()?.counts ?? null);
  protected readonly total = computed(() => this.response()?.total ?? 0);
  protected readonly scope = computed(() => this.response()?.scope ?? 'personal');

  private readonly search$ = new Subject<string>();

  constructor() {
    // 200ms-debounced search stream — each keystroke re-fetches once
    // the user pauses typing.
    this.search$
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.fetch({ silent: false }));

    // Initial load + start the 60s poll. `takeUntilDestroyed` unsubscribes
    // both the search stream and the poll when the widget tears down.
    // The tick is gated on `document.visibilityState === 'visible'` so
    // background tabs and locked mobile screens don't burn battery
    // hammering the API every minute. When the tab comes back to the
    // foreground we do an immediate silent fetch to catch up on
    // whatever changed while we were hidden.
    this.fetch({ silent: false });
    interval(60_000)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (typeof document === 'undefined' || document.visibilityState === 'visible') {
          this.fetch({ silent: true });
        }
      });

    if (typeof document !== 'undefined') {
      const onVisibility = () => {
        if (document.visibilityState === 'visible') {
          this.fetch({ silent: true });
        }
      };
      document.addEventListener('visibilitychange', onVisibility);
      this.destroyRef.onDestroy(() => {
        document.removeEventListener('visibilitychange', onVisibility);
      });
    }

    // Fan-in from the dashboard page's Refresh button. Skip the
    // initial value (tick=0) so mount doesn't fire a duplicate fetch
    // on top of the one queued above.
    effect(() => {
      const tick = this.refreshTick();
      if (tick > 0) {
        this.fetch({ silent: true });
      }
    });
  }

  /** Monotonic tick from the dashboard page's Refresh button. */
  readonly refreshTick = input<number>(0);

  // --- view helpers ------------------------------------------------------

  protected typeMeta(type: FollowupType | null | undefined): { label: string; icon: string } {
    return FOLLOWUP_TYPE_LABELS[type ?? 'other'] ?? FOLLOWUP_TYPE_LABELS.other;
  }

  protected priorityMeta(p: FollowupPriority): { label: string; dot: string; text: string } {
    return PRIORITY_LABELS[p];
  }

  protected countFor(chip: BucketChip): number {
    const c = this.counts();
    return c ? (c[chip.countKey] ?? 0) : 0;
  }

  protected trackByRow(_index: number, row: FollowupItem): string {
    return row.id;
  }

  /** Chip variant for the row's status badge. Overdue is derived
   *  client-side because the payload doesn't tag rows as "overdue"
   *  explicitly — the bucket does. */
  protected statusBadge(row: FollowupItem): { label: string; classes: string } {
    if (row.status === 'done') {
      return {
        label: 'Completed',
        classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
      };
    }
    if (row.status === 'missed') {
      return {
        label: 'Missed',
        classes: 'bg-red-500/10 text-red-400 ring-red-500/20',
      };
    }
    if (row.status === 'cancelled') {
      return {
        label: 'Cancelled',
        classes: 'bg-surface-2 text-muted border-subtle',
      };
    }
    // open — decide Overdue vs Pending from the due_at.
    if (row.due_at && new Date(row.due_at).getTime() < Date.now()) {
      return {
        label: 'Overdue',
        classes: 'bg-red-500/10 text-red-400 ring-red-500/20',
      };
    }
    return {
      label: 'Pending',
      classes: 'bg-amber-50 text-amber-700 ring-amber-200',
    };
  }

  protected openLink(row: FollowupItem): (string | number)[] {
    if (row.linked_entity?.type === 'contact') {
      return ['/user/contacts', row.linked_entity.id];
    }
    if (row.linked_entity?.type === 'lead') {
      return ['/user/leads', row.linked_entity.id];
    }
    return ['/user/tasks', row.id];
  }

  protected dueTimeShort(iso: string | null): string {
    if (!iso) return 'No time';
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return time;
    const day = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    return `${day} ${time}`;
  }

  // --- interactions -----------------------------------------------------

  protected pickBucket(next: FollowupBucket): void {
    if (this.bucket() === next) return;
    this.bucket.set(next);
    this.reschedulingId.set(null);
    this.fetch({ silent: false });
  }

  /** Public API — the dashboard page calls this when a KPI card is
   *  clicked. Same effect as `pickBucket`, but public so parent
   *  components can use it via a template ref. */
  setBucket(next: FollowupBucket): void {
    this.pickBucket(next);
  }

  protected onSearchInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.searchTerm.set(value);
    this.search$.next(value);
  }

  protected toggleFilters(): void {
    this.showFilters.update((v) => !v);
  }

  protected onFilterChanged(): void {
    this.fetch({ silent: false });
  }

  protected clearFilters(): void {
    this.filterType.set('');
    this.filterPriority.set('');
    this.fetch({ silent: false });
  }

  protected onReschedule(row: FollowupItem): void {
    this.reschedulingId.set(row.id);
  }

  protected cancelReschedule(): void {
    this.reschedulingId.set(null);
  }

  protected saveReschedule(row: FollowupItem, isoValue: string): void {
    this.reschedulingId.set(null);
    this.api
      .reschedule(row.id, isoValue)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.fetch({ silent: true }),
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not reschedule.');
        },
      });
  }

  protected onComplete(row: FollowupItem): void {
    if (row.status === 'done') return;
    // Optimistic: flip the row locally + adjust the counters so the
    // click feels instant. Revert on failure.
    this.setOptimisticDone(row.id, true);
    this.api
      .markDone(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.fetch({ silent: true }),
        error: (err: HttpErrorResponse) => {
          this.setOptimisticDone(row.id, false);
          this.error.set(extractApiError(err) ?? 'Could not mark done.');
        },
      });
  }

  /** Only overdue-open rows are eligible for Mark-as-missed. Every
   *  other state (done / cancelled / already-missed / future-open)
   *  hides the button entirely. */
  protected canMarkMissed(row: FollowupItem): boolean {
    if (row.status !== 'open') return false;
    if (!row.due_at) return false;
    return new Date(row.due_at).getTime() < Date.now();
  }

  protected onMarkMissed(row: FollowupItem): void {
    if (!this.canMarkMissed(row)) return;
    this.setOptimisticMissed(row.id, true);
    this.api
      .markMissed(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.fetch({ silent: true }),
        error: (err: HttpErrorResponse) => {
          this.setOptimisticMissed(row.id, false);
          this.error.set(extractApiError(err) ?? 'Could not mark missed.');
        },
      });
  }

  protected refresh(): void {
    this.fetch({ silent: false });
  }

  protected navigateToNewTask(): void {
    this.router.navigate(['/user/tasks'], { queryParams: { new: 1 } });
  }

  // --- fetch ------------------------------------------------------------

  private fetch(opts: { silent: boolean }): void {
    if (opts.silent) {
      this.refreshing.set(true);
    } else {
      this.loading.set(true);
    }
    this.error.set(null);

    this.api
      .list({
        bucket: this.bucket(),
        followup_type: this.filterType() || undefined,
        priority: this.filterPriority() || undefined,
        q: this.searchTerm().trim() || undefined,
        page: 1,
        page_size: 20,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.response.set(resp);
          this.loading.set(false);
          this.refreshing.set(false);
          this.optimisticallyDone.set(new Set());
          this.optimisticallyMissed.set(new Set());
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? "Couldn't load follow-ups.");
          this.loading.set(false);
          this.refreshing.set(false);
        },
      });
  }

  private setOptimisticDone(id: string, value: boolean): void {
    this.optimisticallyDone.update((prev) => {
      const next = new Set(prev);
      if (value) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  private setOptimisticMissed(id: string, value: boolean): void {
    this.optimisticallyMissed.update((prev) => {
      const next = new Set(prev);
      if (value) next.add(id);
      else next.delete(id);
      return next;
    });
  }
}
