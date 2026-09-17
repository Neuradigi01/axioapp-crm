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
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import {
  ABWinnerMetric,
  PairABRequest,
  WorkflowRead,
  WorkflowsApiService,
} from '../workflows-api.service';

const HOLDBACK_PRESETS: Array<{ days: number; label: string; seconds: number }> = [
  { days: 1, label: '1 day', seconds: 86_400 },
  { days: 3, label: '3 days', seconds: 86_400 * 3 },
  { days: 7, label: '7 days', seconds: 86_400 * 7 },
  { days: 14, label: '14 days', seconds: 86_400 * 14 },
  { days: 30, label: '30 days', seconds: 86_400 * 30 },
];

const METRICS: Array<{ value: ABWinnerMetric; label: string }> = [
  { value: 'goal_conversion', label: 'Goal-conversion rate (recommended)' },
  { value: 'reply_rate', label: 'Reply rate' },
  { value: 'open_rate', label: 'Open rate' },
  { value: 'custom', label: 'Custom (manual decision)' },
];

/**
 * Step 18 — pair-A/B modal. Operator picks a draft sibling workflow
 * (filtered to drafts whose trigger event_type set matches the
 * primary), a holdback duration, and a winner-decision metric.
 *
 * The modal validates client-side: sibling must be a draft AND share
 * the primary's `enabled_event_types`. The backend re-validates and
 * returns 422 with a structured reason on edge cases.
 */

@Component({
  selector: 'app-ab-pair-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ab-pair-modal.component.html',
})
export class ABPairModalComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly primary = input.required<WorkflowRead>();

  readonly cancel = output<void>();
  readonly confirm = output<WorkflowRead>();

  readonly siblingId = signal('');
  readonly holdbackSeconds = signal<number>(HOLDBACK_PRESETS[2].seconds);
  readonly metric = signal<ABWinnerMetric>('goal_conversion');
  readonly minRuns = signal<number>(50);

  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly drafts = signal<WorkflowRead[]>([]);

  readonly holdbackPresets = HOLDBACK_PRESETS;
  readonly metrics = METRICS;

  readonly siblingSelectOptions = computed<MobileSelectOption[]>(() =>
    this.eligibleDrafts().map((d) => ({ value: d.id, label: d.name })),
  );
  readonly metricSelectOptions: ReadonlyArray<MobileSelectOption> = METRICS.map((m) => ({
    value: m.value,
    label: m.label,
  }));

  readonly eligibleDrafts = computed(() => {
    const me = this.primary();
    const myTriggers = new Set(me.enabled_event_types || []);
    return this.drafts().filter(
      (d) =>
        d.id !== me.id &&
        d.status === 'draft' &&
        (d.enabled_event_types ?? []).length === myTriggers.size &&
        (d.enabled_event_types ?? []).every((e) => myTriggers.has(e)),
    );
  });

  readonly canSubmit = computed(
    () => this.siblingId() !== '' && this.holdbackSeconds() > 0 && !this.busy(),
  );

  constructor() {
    effect(() => {
      // Trigger the draft list fetch when the modal opens (primary set).
      void this.primary();
      this.loadDrafts();
    });
  }

  private loadDrafts(): void {
    this.api
      .list({ status: 'draft', limit: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => this.drafts.set(resp.items),
        error: (err: HttpErrorResponse) =>
          this.error.set(extractApiError(err) ?? 'Could not load drafts.'),
      });
  }

  onSubmit(event: Event): void {
    event.preventDefault();
    if (!this.canSubmit()) return;
    const payload: PairABRequest = {
      sibling_id: this.siblingId(),
      holdback_seconds: this.holdbackSeconds(),
      metric: this.metric(),
      min_runs_per_variant: this.minRuns(),
    };
    this.busy.set(true);
    this.error.set(null);
    this.api
      .pairAB(this.primary().id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.busy.set(false);
          this.confirm.emit(workflow);
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Pairing failed.');
        },
      });
  }
}
