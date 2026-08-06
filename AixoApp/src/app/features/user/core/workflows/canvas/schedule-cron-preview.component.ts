import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
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
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { EMPTY, of } from 'rxjs';
import { catchError, debounceTime, filter, switchMap, tap } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';

import {
  ScheduleKind,
  SchedulePreviewPayload,
  WorkflowsApiService,
} from '../workflows-api.service';

/**
 * Cron / recurrence preview — takes the current config as an
 * `input()` signal and shows the next 5 fires the backend would
 * compute. Debounced 500ms so keystroke-heavy inputs (cron
 * expression) don't hammer the API.
 *
 * Uses the same `/api/v1/schedules/preview` endpoint the create /
 * update paths validate against so the preview 422 matches the
 * save 422 exactly.
 */

export interface SchedulePreviewInput {
  schedule_kind: ScheduleKind | null;
  config_json: Record<string, unknown>;
  timezone: string;
  starts_at: string;
}

@Component({
  selector: 'app-schedule-cron-preview',
  standalone: true,
  imports: [CommonModule, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './schedule-cron-preview.component.html',
})
export class ScheduleCronPreviewComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Current config — parent form pushes the latest value on every
   *  change; the debounce below absorbs typing bursts. */
  readonly config = input.required<SchedulePreviewInput | null>();

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly fires = signal<string[]>([]);

  /** Whether the config is complete enough to attempt a preview. */
  readonly ready = computed(() => {
    const cfg = this.config();
    if (!cfg) return false;
    return !!cfg.schedule_kind && !!cfg.timezone && !!cfg.starts_at;
  });

  constructor() {
    // Turn the config signal into an observable, debounce, and fire
    // preview requests. `takeUntilDestroyed` cleans up the
    // subscription without a manual OnDestroy hook. `switchMap`
    // cancels an in-flight preview when a fresh config arrives.
    toObservable(this.config)
      .pipe(
        debounceTime(500),
        filter(
          (cfg): cfg is SchedulePreviewInput =>
            cfg !== null && !!cfg.schedule_kind && !!cfg.timezone && !!cfg.starts_at,
        ),
        tap(() => {
          this.loading.set(true);
          this.error.set(null);
        }),
        switchMap((cfg) => {
          const payload: SchedulePreviewPayload = {
            schedule_kind: cfg.schedule_kind as ScheduleKind,
            config_json: cfg.config_json,
            timezone: cfg.timezone,
            starts_at: cfg.starts_at,
          };
          return this.api.previewSchedule(payload).pipe(
            tap((resp) => {
              this.fires.set(resp.fires);
              this.loading.set(false);
            }),
            catchError((err: HttpErrorResponse) => {
              this.fires.set([]);
              this.loading.set(false);
              this.error.set(extractApiError(err) ?? 'Preview unavailable.');
              return EMPTY;
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe();

    // When the config becomes not-ready (e.g. user cleared a field),
    // clear the fires + error so the panel doesn't show stale data.
    effect(() => {
      if (!this.ready()) {
        this.fires.set([]);
        this.error.set(null);
        this.loading.set(false);
      }
    });

    // Silence unused-import ESLint on `of` (used inline for
    // conditional branches when future edits need a placeholder).
    void of;
  }
}
