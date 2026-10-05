import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Input,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';

import { Call, CallDirection, CallOutcome, CallsApiService } from '../calls-api.service';
import { formatCallDuration, formatCallTime } from '../call-format.util';
import { EmptyStateComponent } from '../../shared/empty-state/empty-state.component';
import { CallRecordingPlayerComponent } from '../call-recording-player.component';
import { LogCallModalComponent } from '../log-call-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../shared/components/toast/toast.service';

/**
 * Call Logs tab — table of every call (newest first) + "Log call" button
 * that opens the shared `LogCallModalComponent`. Outcomes are loaded
 * once and shared with the modal as an input.
 */
@Component({
  selector: 'app-call-logs-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LogCallModalComponent,
    CallRecordingPlayerComponent,
    LucideAngularModule,
    EmptyStateComponent,
    RouterLink,
  ],
  templateUrl: './logs.component.html',
})
export class CallLogsTabComponent {
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);

  /** Rows per fetch (server cap); "Load more" pulls the next page. */
  private static readonly PAGE_SIZE = 200;
  protected readonly page = signal(1);
  protected readonly total = signal(0);
  protected readonly loadingMore = signal(false);
  protected readonly hasMore = computed(() => this.items().length < this.total());

  /** Bumped counter from the page header's "Log call" button. Any
   *  value change (except the initial 0 → 0 during first render)
   *  opens the modal. Setter form so we can observe changes. */
  @Input() set openModalTrigger(v: number) {
    if (v > 0 && v !== this._lastTrigger) {
      this._lastTrigger = v;
      this.openModal();
    }
  }
  private _lastTrigger = 0;

  protected readonly items = signal<Call[]>([]);
  protected readonly outcomes = signal<CallOutcome[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  /** Set when `listOutcomes()` fails. Without outcomes, the Log Call
   *  modal's outcome-picker picklist validator rejects every choice —
   *  operators need to see WHY, not just a silent broken picker. */
  protected readonly outcomesError = signal<string | null>(null);
  protected readonly modalOpen = signal(false);

  /** Direction filter chips — `''` = all (server-side `direction`). */
  protected readonly direction = signal<'' | CallDirection>('');
  protected readonly directionChips: ReadonlyArray<{ v: '' | CallDirection; label: string }> = [
    { v: '', label: 'All' },
    { v: 'in', label: 'Incoming' },
    { v: 'out', label: 'Outgoing' },
  ];

  protected setDirection(v: '' | CallDirection): void {
    if (this.direction() === v) return;
    this.direction.set(v);
    this.reload();
  }

  protected readonly outcomeById = computed(() => {
    const m = new Map<string, CallOutcome>();
    for (const o of this.outcomes()) m.set(o.id, o);
    return m;
  });

  constructor() {
    this.reload();
    this.api
      .listOutcomes()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.outcomes.set(rows);
          this.outcomesError.set(null);
        },
        error: (err: HttpErrorResponse) => {
          // Empty outcome list makes the Log Call modal's outcome
          // picklist validator reject every value the rep picks —
          // record the reason so the tab can surface it inline.
          this.outcomesError.set(
            extractApiError(err) ?? 'Could not load call outcomes — logging a call may fail.',
          );
        },
      });

    // Honour `/user/calls?new=1` (dashboard quick-action) so landing
    // on the call-center from elsewhere opens the log-call modal
    // directly on the default (Logs) tab. Strip the param after.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      if (params.get('new') !== null && !this.modalOpen()) {
        this.openModal();
        this.router.navigate([], {
          relativeTo: this.route,
          queryParams: { new: null },
          queryParamsHandling: 'merge',
          replaceUrl: true,
        });
      }
    });
  }

  /** Monotonic request id — bumped on every `reload()`, checked in the
   *  response callback so a slow earlier response can't overwrite a
   *  faster later one when the user changes filters / tabs quickly. */
  private reloadSeq = 0;

  protected reload(): void {
    const seq = ++this.reloadSeq;
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listCalls({
        page: 1,
        size: CallLogsTabComponent.PAGE_SIZE,
        direction: this.direction() || undefined,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (seq !== this.reloadSeq) return;
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.page.set(1);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.reloadSeq) return;
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load calls.');
        },
      });
  }

  /** Append the next page. Shares `reloadSeq` so a reload mid-flight
   *  discards this (now stale) page. */
  protected loadMore(): void {
    if (this.loadingMore() || !this.hasMore()) return;
    const seq = this.reloadSeq;
    const next = this.page() + 1;
    this.loadingMore.set(true);
    this.api
      .listCalls({
        page: next,
        size: CallLogsTabComponent.PAGE_SIZE,
        direction: this.direction() || undefined,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (seq !== this.reloadSeq) return;
          // New calls logged meanwhile shift pages; skip duplicates.
          const seen = new Set(this.items().map((c) => c.id));
          this.items.update((cur) => [...cur, ...resp.items.filter((c) => !seen.has(c.id))]);
          this.total.set(resp.total);
          this.page.set(next);
          this.loadingMore.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.reloadSeq) return;
          this.loadingMore.set(false);
          this.toast.error('Could not load more calls', {
            subtitle: extractApiError(err) ?? 'Please try again.',
          });
        },
      });
  }

  protected openModal(): void {
    this.modalOpen.set(true);
  }

  protected onSaved(): void {
    this.modalOpen.set(false);
    this.reload();
    this.toast.success('Call logged');
  }

  protected onCancel(): void {
    this.modalOpen.set(false);
  }

  protected readonly formatDuration = formatCallDuration;
  protected readonly formatTimestamp = formatCallTime;

  protected outcomeFor(call: Call): CallOutcome | null {
    return call.outcome_id ? (this.outcomeById().get(call.outcome_id) ?? null) : null;
  }
}
