import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import {
  ConcurrencyPolicy,
  OnMissedPolicy,
  Schedule,
  ScheduleCreatePayload,
  ScheduleKind,
  ScheduleUpdatePayload,
  WorkflowsApiService,
} from '../workflows-api.service';

import {
  ScheduleCronPreviewComponent,
  SchedulePreviewInput,
} from './schedule-cron-preview.component';

/**
 * Config modal — used for both **create** (mode='create') and
 * **edit** (mode='edit'). Kind-conditional fields via `@switch` in
 * the template. Reactive form with a single flat FormGroup — cheap
 * to reason about + easy to prefill on edit.
 *
 * On save:
 *   - Create → POST /workflows/{id}/schedules
 *   - Edit → PATCH /schedules/{id} with If-Match=<updated_at>
 *     (server 409 if stale — parent handles the toast + refetch)
 *
 * The modal owns its own error state so the parent doesn't have to
 * juggle both the form + the save-in-flight state.
 */

const WEEKDAY_OPTIONS: ReadonlyArray<{ code: string; label: string }> = [
  { code: 'mon', label: 'Mon' },
  { code: 'tue', label: 'Tue' },
  { code: 'wed', label: 'Wed' },
  { code: 'thu', label: 'Thu' },
  { code: 'fri', label: 'Fri' },
  { code: 'sat', label: 'Sat' },
  { code: 'sun', label: 'Sun' },
];

const SCHEDULE_KIND_OPTIONS: ReadonlyArray<{ value: ScheduleKind; label: string }> = [
  { value: 'once', label: 'Run once' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'interval', label: 'Custom interval' },
  { value: 'cron', label: 'Advanced (cron expression)' },
];

const INTERVAL_UNIT_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'minutes', label: 'minutes' },
  { value: 'hours', label: 'hours' },
  { value: 'days', label: 'days' },
];

const ON_MISSED_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'skip', label: 'Skip missed — resume on next scheduled fire' },
  { value: 'run_once', label: 'Run once on recovery' },
  { value: 'backfill_all', label: 'Backfill every missed fire (rate-limited)' },
];

const CONCURRENCY_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'forbid', label: 'Skip new fire (default — prevents double-send)' },
  { value: 'allow', label: 'Fire anyway (parallel runs allowed)' },
  { value: 'replace', label: 'Cancel in-flight run and start new' },
];

function localIsoNowPlus(minutes: number): string {
  // <input type="datetime-local"> is naive-local time (no tz). Build
  // in local time so the display matches the operator's wall clock —
  // `.toISOString()` would emit UTC and pre-shift the value by the
  // browser's tz offset.
  const d = new Date(Date.now() + minutes * 60 * 1000);
  const pad = (n: number) => n.toString().padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function toIsoUtc(dateTimeLocal: string): string {
  // datetime-local values are naive local time — construct as local
  // then serialize as ISO with tz offset. Backend accepts either
  // shape but we send UTC for consistency.
  if (!dateTimeLocal) return '';
  return new Date(dateTimeLocal).toISOString();
}

function fromIsoToLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  // Round to nearest minute to fit the datetime-local input.
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

@Component({
  selector: 'app-schedule-config-modal',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    LucideAngularModule,
    ScheduleCronPreviewComponent,
    MobileSelectComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './schedule-config-modal.component.html',
})
export class ScheduleConfigModalComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  /** Parent-controlled visibility. */
  readonly open = input<boolean>(false);
  /** Owning workflow — required for create. */
  readonly workflowId = input.required<string>();
  /** When set, modal is in edit mode; when null, create mode. */
  readonly editing = input<Schedule | null>(null);
  /** Default timezone hint (org tz, resolved by parent). Falls back
   *  to the browser's tz. */
  readonly defaultTimezone = input<string>('UTC');

  readonly close = output<void>();
  readonly saved = output<Schedule>();

  readonly saving = signal(false);
  readonly error = signal<string | null>(null);

  readonly kindOptions = SCHEDULE_KIND_OPTIONS;
  readonly weekdayOptions = WEEKDAY_OPTIONS;
  readonly timezoneOptions = signal<string[]>([]);
  readonly intervalUnitOptions = INTERVAL_UNIT_OPTIONS;
  readonly onMissedOptions = ON_MISSED_OPTIONS;
  readonly concurrencyOptions = CONCURRENCY_OPTIONS;
  readonly kindSelectOptions = computed<MobileSelectOption[]>(() =>
    this.kindOptions.map((o) => ({ value: o.value, label: o.label })),
  );

  readonly form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    schedule_kind: this.fb.nonNullable.control<ScheduleKind>('daily', Validators.required),
    timezone: ['UTC', Validators.required],
    starts_at: [localIsoNowPlus(5), Validators.required],
    end_at: [''],
    max_runs: this.fb.control<number | null>(null),
    on_missed: this.fb.nonNullable.control<OnMissedPolicy>('skip'),
    concurrency_policy: this.fb.nonNullable.control<ConcurrencyPolicy>('forbid'),
    // Kind-specific fields — all present, only the relevant subset
    // renders + participates in the payload.
    once_at: [''],
    daily_time: ['09:00'],
    weekly_days: [[] as string[]],
    weekly_time: ['09:00'],
    monthly_day_of_month: [1],
    monthly_time: ['09:00'],
    interval_every: [15],
    interval_unit: this.fb.nonNullable.control<'minutes' | 'hours' | 'days'>('minutes'),
    cron_expression: ['0 9 * * 1'],
  });

  /** Signalised form value — feeds the cron preview component. */
  readonly formValue = signal<typeof this.form.value>(this.form.getRawValue());

  /** Config-shape the preview endpoint expects. Recomputed on every
   *  form change so the child debounces. */
  readonly previewInput = computed<SchedulePreviewInput | null>(() => {
    const v = this.formValue();
    if (!v.schedule_kind || !v.timezone || !v.starts_at) return null;
    return {
      schedule_kind: v.schedule_kind,
      config_json: this.buildConfigJson(v),
      timezone: v.timezone,
      starts_at: toIsoUtc(v.starts_at),
    };
  });

  constructor() {
    // Populate timezone dropdown once — the Intl API is O(list).
    this.timezoneOptions.set(this.loadTimezones());

    // Keep the signalised form value fresh so the computed
    // `previewInput` and template observers react.
    this.form.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.formValue.set(this.form.getRawValue()));

    // Prefill when the parent opens the modal.
    effect(() => {
      const opened = this.open();
      if (!opened) return;
      this.error.set(null);
      const editing = this.editing();
      if (editing) {
        this.prefillFromSchedule(editing);
      } else {
        this.resetForCreate();
      }
    });
  }

  private loadTimezones(): string[] {
    const anyIntl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
    if (typeof anyIntl.supportedValuesOf === 'function') {
      try {
        return anyIntl.supportedValuesOf('timeZone');
      } catch {
        // fall through
      }
    }
    // Fallback — a small hand-picked list. Better than crashing on
    // an older browser.
    return ['UTC', 'Asia/Kolkata', 'America/New_York', 'Europe/London', 'Asia/Tokyo'];
  }

  private resetForCreate(): void {
    this.form.reset({
      name: '',
      schedule_kind: 'daily',
      timezone: this.defaultTimezone(),
      starts_at: localIsoNowPlus(5),
      end_at: '',
      max_runs: null,
      on_missed: 'skip',
      concurrency_policy: 'forbid',
      once_at: '',
      daily_time: '09:00',
      weekly_days: [],
      weekly_time: '09:00',
      monthly_day_of_month: 1,
      monthly_time: '09:00',
      interval_every: 15,
      interval_unit: 'minutes',
      cron_expression: '0 9 * * 1',
    });
    this.formValue.set(this.form.getRawValue());
  }

  private prefillFromSchedule(s: Schedule): void {
    const cfg = s.config_json as Record<string, unknown>;
    this.form.reset({
      name: s.name,
      schedule_kind: s.schedule_kind,
      timezone: s.timezone,
      starts_at: fromIsoToLocalInput(s.starts_at),
      end_at: fromIsoToLocalInput(s.end_at),
      max_runs: s.max_runs,
      on_missed: s.on_missed,
      concurrency_policy: s.concurrency_policy,
      once_at: (cfg['at'] as string) ?? '',
      daily_time: (cfg['time'] as string) ?? '09:00',
      weekly_days: (cfg['days'] as string[]) ?? [],
      weekly_time: (cfg['time'] as string) ?? '09:00',
      monthly_day_of_month: (cfg['day_of_month'] as number) ?? 1,
      monthly_time: (cfg['time'] as string) ?? '09:00',
      interval_every: (cfg['every'] as number) ?? 15,
      interval_unit: (cfg['unit'] as 'minutes' | 'hours' | 'days' | undefined) ?? 'minutes',
      cron_expression: (cfg['expression'] as string) ?? '0 9 * * 1',
    });
    this.formValue.set(this.form.getRawValue());
  }

  toggleWeekday(code: string): void {
    const current = this.form.controls.weekly_days.value ?? [];
    const next = current.includes(code) ? current.filter((c) => c !== code) : [...current, code];
    this.form.controls.weekly_days.setValue(next);
  }

  isWeekdaySelected(code: string): boolean {
    return (this.form.controls.weekly_days.value ?? []).includes(code);
  }

  private buildConfigJson(v: typeof this.form.value): Record<string, unknown> {
    switch (v.schedule_kind) {
      case 'once':
        return { at: toIsoUtc(v.once_at || '') };
      case 'daily':
        return { time: v.daily_time };
      case 'weekly':
        return { days: v.weekly_days ?? [], time: v.weekly_time };
      case 'monthly':
        return {
          day_of_month: v.monthly_day_of_month ?? 1,
          time: v.monthly_time,
        };
      case 'interval':
        return { every: v.interval_every ?? 1, unit: v.interval_unit };
      case 'cron':
        return { expression: v.cron_expression };
      default:
        return {};
    }
  }

  onSubmit(event: Event): void {
    event.preventDefault();
    if (this.saving()) return;
    if (this.form.invalid) {
      this.error.set('Please fill in every required field.');
      return;
    }
    const v = this.form.getRawValue();
    const editing = this.editing();
    if (editing) {
      this.doPatch(editing, v);
    } else {
      this.doCreate(v);
    }
  }

  private doCreate(v: typeof this.form.value): void {
    const payload: ScheduleCreatePayload = {
      name: v.name!,
      schedule_kind: v.schedule_kind!,
      config_json: this.buildConfigJson(v),
      timezone: v.timezone!,
      starts_at: toIsoUtc(v.starts_at!),
      end_at: v.end_at ? toIsoUtc(v.end_at) : null,
      max_runs: v.max_runs ?? null,
      on_missed: v.on_missed!,
      concurrency_policy: v.concurrency_policy!,
    };
    this.saving.set(true);
    this.error.set(null);
    this.api
      .createSchedule(this.workflowId(), payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (created) => {
          this.saving.set(false);
          this.saved.emit(created);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.error.set(extractApiError(err) ?? 'Could not save schedule.');
        },
      });
  }

  private doPatch(editing: Schedule, v: typeof this.form.value): void {
    const payload: ScheduleUpdatePayload = {
      name: v.name!,
      schedule_kind: v.schedule_kind!,
      config_json: this.buildConfigJson(v),
      timezone: v.timezone!,
      starts_at: toIsoUtc(v.starts_at!),
      end_at: v.end_at ? toIsoUtc(v.end_at) : null,
      max_runs: v.max_runs ?? null,
      on_missed: v.on_missed!,
      concurrency_policy: v.concurrency_policy!,
    };
    this.saving.set(true);
    this.error.set(null);
    // ETag = the schedule's `updated_at` sans micros & tz (server
    // format). Backend accepts a naive UTC ISO; also accepts the
    // fresh header-echoed value.
    const etag = editing.updated_at.replace(/\.\d+/, '').replace(/[+-]\d\d:?\d\d$/, '');
    this.api
      .updateSchedule(editing.id, etag, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.saved.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          if (err.status === 409) {
            this.error.set(
              'This schedule was changed by someone else. Close and reopen to see the current version.',
            );
          } else if (err.status === 428) {
            this.error.set('Missing If-Match header (client bug — please reload).');
          } else {
            this.error.set(extractApiError(err) ?? 'Could not save schedule.');
          }
        },
      });
  }
}
