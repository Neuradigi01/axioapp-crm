import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { CallOutcome, CallsApiService } from '../../calls/calls-api.service';
import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { commonValidators } from '../../shared/validators';

/** Colours offered for an outcome's badge. */
const OUTCOME_COLORS: readonly string[] = [
  '#10b981',
  '#0ea5e9',
  '#6366f1',
  '#8b5cf6',
  '#f59e0b',
  '#f97316',
  '#ef4444',
  '#6b7280',
];

/** Mirrors `MAX_OUTCOMES_PER_ORG` in api/src/app/core/calls/service.py. */
const MAX_OUTCOMES = 50;
const LABEL_MAX = 128;

/** `Call Back Later` → `call_back_later`; a numeric suffix keeps it unique. */
function outcomeKey(label: string, taken: ReadonlySet<string>): string {
  const base =
    label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 56) || 'outcome';
  let key = base;
  for (let n = 2; taken.has(key); n++) key = `${base}_${n}`;
  return key;
}

/**
 * Settings → Call Outcomes. Admins manage the options agents pick from
 * in "Log a call": add, rename, recolour, reorder and delete. Gated by
 * `calls.outcomes.manage` (the tab is hidden without it and the API
 * enforces the same key).
 */
@Component({
  selector: 'app-settings-call-outcomes-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './call-outcomes-tab.component.html',
})
export class CallOutcomesTabComponent {
  private readonly api = inject(CallsApiService);
  private readonly fb = inject(FormBuilder);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmDialogService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly colors = OUTCOME_COLORS;
  protected readonly maxOutcomes = MAX_OUTCOMES;
  protected readonly labelMax = LABEL_MAX;

  protected readonly outcomes = signal<CallOutcome[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly busy = signal(false);
  /** Id of the row being edited inline, or null. */
  protected readonly editingId = signal<string | null>(null);
  protected readonly atLimit = computed(() => this.outcomes().length >= MAX_OUTCOMES);

  protected readonly addForm = this.fb.nonNullable.group({
    label: ['', [commonValidators.trimmedRequired, commonValidators.maxLength(LABEL_MAX)]],
    color: [OUTCOME_COLORS[0]],
  });

  protected readonly editForm = this.fb.nonNullable.group({
    label: ['', [commonValidators.trimmedRequired, commonValidators.maxLength(LABEL_MAX)]],
    color: [OUTCOME_COLORS[0]],
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listOutcomes()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.outcomes.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          const msg = extractApiError(err) ?? 'Could not load call outcomes.';
          this.loading.set(false);
          this.loadError.set(msg);
          this.toast.error('Could not load call outcomes', { subtitle: msg });
        },
      });
  }

  /** Inline error for a label control, or null while untouched / valid. */
  protected labelError(form: 'add' | 'edit'): string | null {
    const ctrl = (form === 'add' ? this.addForm : this.editForm).controls.label;
    if (!ctrl.touched) return null;
    if (ctrl.errors?.['required']) return 'Enter a name for the outcome.';
    if (ctrl.errors?.['maxlength']) return `Keep it under ${LABEL_MAX} characters.`;
    const clash = this.duplicateOf(ctrl.value, form === 'edit' ? this.editingId() : null);
    return clash ? `"${clash.label}" already exists.` : null;
  }

  protected add(): void {
    this.addForm.markAllAsTouched();
    const label = this.addForm.controls.label.value.trim().replace(/\s+/g, ' ');
    if (this.addForm.invalid || this.duplicateOf(label, null)) {
      this.toast.warn('Could not add call outcome', {
        subtitle: this.labelError('add') ?? null,
      });
      return;
    }
    if (this.atLimit()) {
      this.toast.warn('Could not add call outcome', {
        subtitle: `You can have at most ${MAX_OUTCOMES} call outcomes.`,
      });
      return;
    }
    const rows = this.outcomes();
    const payload = {
      key: outcomeKey(label, new Set(rows.map((o) => o.key))),
      label,
      color: this.addForm.controls.color.value,
      display_order: rows.reduce((max, o) => Math.max(max, o.display_order), 0) + 10,
    };
    this.busy.set(true);
    this.api
      .createOutcome(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (created) => {
          this.busy.set(false);
          this.outcomes.set([...rows, created]);
          this.addForm.reset({ label: '', color: OUTCOME_COLORS[0] });
          this.toast.success('Call outcome added', { subtitle: created.label });
        },
        error: (err: HttpErrorResponse) => this.fail('Could not add call outcome', err),
      });
  }

  protected startEdit(outcome: CallOutcome): void {
    this.editingId.set(outcome.id);
    this.editForm.reset({ label: outcome.label, color: outcome.color });
  }

  protected cancelEdit(): void {
    this.editingId.set(null);
  }

  protected saveEdit(outcome: CallOutcome): void {
    this.editForm.markAllAsTouched();
    const label = this.editForm.controls.label.value.trim().replace(/\s+/g, ' ');
    if (this.editForm.invalid || this.duplicateOf(label, outcome.id)) {
      this.toast.warn('Could not update call outcome', {
        subtitle: this.labelError('edit') ?? null,
      });
      return;
    }
    const color = this.editForm.controls.color.value;
    if (label === outcome.label && color === outcome.color) {
      this.editingId.set(null);
      this.toast.info('No changes to save', { subtitle: outcome.label });
      return;
    }
    this.busy.set(true);
    this.api
      .updateOutcome(outcome.id, { label, color })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.busy.set(false);
          this.editingId.set(null);
          this.outcomes.set(this.outcomes().map((o) => (o.id === updated.id ? updated : o)));
          this.toast.success('Call outcome updated', { subtitle: updated.label });
        },
        error: (err: HttpErrorResponse) => this.fail('Could not update call outcome', err),
      });
  }

  /** Move the outcome one place up (-1) or down (+1) and persist the
   *  new positions of every row whose order changed. */
  protected move(index: number, delta: -1 | 1): void {
    const rows = [...this.outcomes()];
    const target = index + delta;
    if (target < 0 || target >= rows.length) return;
    [rows[index], rows[target]] = [rows[target], rows[index]];
    const changed = rows
      .map((o, i) => ({ outcome: o, order: (i + 1) * 10 }))
      .filter(({ outcome, order }) => outcome.display_order !== order);
    this.busy.set(true);
    forkJoin(
      changed.map(({ outcome, order }) =>
        this.api.updateOutcome(outcome.id, { display_order: order }),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.busy.set(false);
          const byId = new Map(updated.map((o) => [o.id, o]));
          this.outcomes.set(rows.map((o) => byId.get(o.id) ?? o));
          this.toast.success('Call outcome order saved');
        },
        error: (err: HttpErrorResponse) => {
          this.fail('Could not reorder call outcomes', err);
          this.reload();
        },
      });
  }

  protected async remove(outcome: CallOutcome): Promise<void> {
    const ok = await this.confirm.ask({
      title: `Delete "${outcome.label}"?`,
      body:
        'Agents will no longer be able to pick it. Calls already logged with this ' +
        'outcome keep their history but will show no outcome.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.busy.set(true);
    this.api
      .deleteOutcome(outcome.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.outcomes.set(this.outcomes().filter((o) => o.id !== outcome.id));
          this.toast.success('Call outcome deleted', { subtitle: outcome.label });
        },
        error: (err: HttpErrorResponse) => this.fail('Could not delete call outcome', err),
      });
  }

  private duplicateOf(label: string, exceptId: string | null): CallOutcome | undefined {
    const wanted = label.trim().replace(/\s+/g, ' ').toLowerCase();
    if (!wanted) return undefined;
    return this.outcomes().find((o) => o.id !== exceptId && o.label.toLowerCase() === wanted);
  }

  private fail(title: string, err: HttpErrorResponse): void {
    this.busy.set(false);
    this.toast.error(title, { subtitle: extractApiError(err) ?? 'Please try again.' });
  }
}
