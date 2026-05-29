import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';

import {
  Call,
  CallOutcome,
  CallsApiService,
} from '../calls-api.service';
import { LogCallModalComponent } from '../log-call-modal.component';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Call Logs tab â€” table of every call (newest first) + "Log call" button
 * that opens the shared `LogCallModalComponent`. Outcomes are loaded
 * once and shared with the modal as an input.
 */
@Component({
  selector: 'app-call-logs-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LogCallModalComponent],
  templateUrl: './logs.component.html',
})
export class CallLogsTabComponent {
  private readonly api = inject(CallsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly items = signal<Call[]>([]);
  protected readonly outcomes = signal<CallOutcome[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly modalOpen = signal(false);

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
        next: (rows) => this.outcomes.set(rows),
        error: () => {
          /* outcomes aren't fatal â€” leave list empty */
        },
      });

    // Honour `/user/calls?new=1` (dashboard quick-action) so landing
    // on the call-center from elsewhere opens the log-call modal
    // directly on the default (Logs) tab. Strip the param after.
    this.route.queryParamMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
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

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listCalls({ size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load calls.',
          );
        },
      });
  }

  protected openModal(): void {
    this.modalOpen.set(true);
  }

  protected onSaved(): void {
    this.modalOpen.set(false);
    this.reload();
  }

  protected onCancel(): void {
    this.modalOpen.set(false);
  }

  protected formatDuration(sec: number): string {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m === 0) return `${s}s`;
    return `${m}m ${s}s`;
  }

  protected formatTimestamp(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  protected outcomeFor(call: Call): CallOutcome | null {
    return call.outcome_id ? this.outcomeById().get(call.outcome_id) ?? null : null;
  }

}
