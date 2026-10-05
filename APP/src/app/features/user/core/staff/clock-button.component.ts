import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '@shared/components/toast/toast.service';

import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { AttendanceOut, StaffApiService } from './staff-api.service';

/** How often the "On shift · 2h 14m" label re-renders. */
const TICK_MS = 30_000;

/**
 * Header Clock In / Clock Out button. Every signed-in user clocks only
 * themselves in via `/staff/me/*`; the resulting sessions feed the
 * Staff → Attendance tab and the "Present today" KPI.
 *
 * Several sessions per day are allowed (e.g. around lunch); the server
 * only refuses a second open session. A session left open from a
 * previous day shows its start time so the user can close it.
 */
@Component({
  selector: 'app-clock-button',
  standalone: true,
  imports: [LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (loaded()) {
      @if (openSession(); as session) {
        <button
          type="button"
          class="inline-flex h-[34px] items-center gap-1.5 rounded-[9px] border border-emerald-500/30 bg-emerald-500/10 px-2.5 text-xs font-medium text-emerald-600 transition hover:bg-emerald-500/20 disabled:opacity-60 dark:text-emerald-400"
          [disabled]="busy()"
          [attr.aria-label]="'Clocked in ' + sinceLabel() + '. Click to clock out.'"
          [title]="'Clocked in ' + sinceLabel() + ' — click to clock out'"
          (click)="clockOut()"
        >
          <span class="relative flex h-2 w-2">
            <span
              class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60"
            ></span>
            <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
          </span>
          @if (startedToday()) {
            <span class="hidden sm:inline">On shift ·</span>
            <span class="tabular-nums">{{ elapsedLabel() }}</span>
          } @else {
            <span class="hidden sm:inline">Clocked in {{ sinceLabel() }}</span>
            <span class="sm:hidden">Clock out</span>
          }
        </button>
      } @else {
        <button
          type="button"
          class="inline-flex h-[34px] items-center gap-1.5 rounded-[9px] border border-subtle bg-app px-2.5 text-xs font-medium text-muted transition hover:bg-surface-2 hover:text-default disabled:opacity-60"
          [disabled]="busy()"
          aria-label="Clock in"
          (click)="clockIn()"
        >
          <lucide-icon name="clock" class="h-4 w-4" />
          <span class="hidden sm:inline">Clock in</span>
        </button>
      }
    }
  `,
})
export class ClockButtonComponent implements OnInit {
  private readonly api = inject(StaffApiService);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly openSession = signal<AttendanceOut | null>(null);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  private readonly now = signal(Date.now());

  private readonly startedAt = computed(() => {
    const s = this.openSession();
    return s ? new Date(s.clock_in_at) : null;
  });

  protected readonly startedToday = computed(() => {
    const start = this.startedAt();
    return start !== null && start.toDateString() === new Date(this.now()).toDateString();
  });

  protected readonly elapsedLabel = computed(() => {
    const start = this.startedAt();
    if (!start) return '';
    const minutes = Math.max(0, Math.floor((this.now() - start.getTime()) / 60_000));
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  });

  protected readonly sinceLabel = computed(() => {
    const start = this.startedAt();
    if (!start) return '';
    const time = start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (this.startedToday()) return `at ${time}`;
    const yesterday = new Date(this.now());
    yesterday.setDate(yesterday.getDate() - 1);
    if (start.toDateString() === yesterday.toDateString()) return `since yesterday ${time}`;
    const day = start.toLocaleDateString([], { day: 'numeric', month: 'short' });
    return `since ${day} ${time}`;
  });

  ngOnInit(): void {
    this.refresh();
    const timer = setInterval(() => this.now.set(Date.now()), TICK_MS);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  protected clockIn(): void {
    this.busy.set(true);
    this.api
      .myClockIn()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.busy.set(false);
          this.now.set(Date.now());
          this.openSession.set(row);
          this.toast.success('Clocked in');
        },
        error: (err: HttpErrorResponse) => this.onActionError(err, 'Could not clock in'),
      });
  }

  protected async clockOut(): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: 'Clock out now?',
      body: `You clocked in ${this.sinceLabel()}.`,
      confirmLabel: 'Clock out',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;

    this.busy.set(true);
    this.api
      .myClockOut()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.busy.set(false);
          this.openSession.set(null);
          this.toast.success('Clocked out', {
            subtitle: row.hours !== null ? `${Number(row.hours).toFixed(2)} hrs recorded` : null,
          });
        },
        error: (err: HttpErrorResponse) => this.onActionError(err, 'Could not clock out'),
      });
  }

  private refresh(): void {
    this.api
      .myOpenAttendance()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.openSession.set(row);
          this.loaded.set(true);
        },
        // Hide the button rather than show a wrong state.
        error: () => this.loaded.set(false),
      });
  }

  /** 409 (already clocked in) / 404 (already clocked out) mean another
   *  tab changed the state — resync instead of leaving a stale button. */
  private onActionError(err: HttpErrorResponse, title: string): void {
    this.busy.set(false);
    if (err.status === 409 || err.status === 404) {
      this.refresh();
      return;
    }
    this.toast.error(title, { subtitle: extractApiError(err) });
  }
}
