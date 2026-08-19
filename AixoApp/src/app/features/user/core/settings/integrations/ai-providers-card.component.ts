/**
 * Settings → Integrations → AI Providers card
 * (``tasks/ai-assistants`` Step 3).
 *
 * Two panels stacked:
 *
 *   1. **Keys** — one row per stored key: provider · label · masked
 *      last-4 · test status pill (with tooltip on hover for failed) ·
 *      Test / Delete buttons. Empty state prompts "+ Add Key".
 *
 *   2. **Budget** — daily + monthly USD caps + spent progress bars.
 *      Save button debounced; standard amber banner when spent >
 *      80% of either cap (feedback_standard_warning_banner_pattern).
 *
 * Add / delete + reassign flows delegate to the two modal
 * components; API calls go through :class:`AiProvidersApiService`.
 *
 * Everything is gated server-side by ``ai_providers.manage``. The
 * parent integrations page hides this card unless the caller holds
 * the key.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { debounceTime } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  AiProviderKey,
  AiProviderKeyReferencedError,
  AiProvidersApiService,
  OrgAiCostBudget,
} from './ai-providers-api.service';
import { AiProvidersAddKeyModalComponent } from './ai-providers-add-key-modal.component';
import { AiProvidersReassignModalComponent } from './ai-providers-reassign-modal.component';

@Component({
  selector: 'app-ai-providers-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    AiProvidersAddKeyModalComponent,
    AiProvidersReassignModalComponent,
  ],
  templateUrl: './ai-providers-card.component.html',
})
export class AiProvidersCardComponent {
  private readonly api = inject(AiProvidersApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly keys = signal<AiProviderKey[]>([]);
  protected readonly budget = signal<OrgAiCostBudget | null>(null);

  protected readonly addModalOpen = signal(false);
  protected readonly testingId = signal<string | null>(null);
  protected readonly deletingId = signal<string | null>(null);
  protected readonly rowError = signal<{ id: string; message: string } | null>(null);

  /** When set, the reassign modal renders with these props. */
  protected readonly reassignTarget = signal<{
    from: AiProviderKey;
    count: number;
  } | null>(null);

  protected readonly budgetForm = this.fb.nonNullable.group({
    daily_cap_usd: this.fb.nonNullable.control<number>(10, {
      validators: [Validators.min(0)],
    }),
    monthly_cap_usd: this.fb.nonNullable.control<number>(200, {
      validators: [Validators.min(0)],
    }),
  });
  protected readonly budgetSaving = signal(false);
  protected readonly budgetSavedAt = signal<number | null>(null);
  protected readonly budgetError = signal<string | null>(null);

  /** Candidates for the reassign modal — every other live key. */
  protected readonly reassignCandidates = computed<AiProviderKey[]>(() => {
    const from = this.reassignTarget()?.from;
    if (!from) return [];
    return this.keys().filter((k) => k.id !== from.id && !k.revoked_at);
  });

  protected readonly dailyPct = computed<number>(() => {
    const b = this.budget();
    if (!b) return 0;
    const cap = Number(b.daily_cap_usd);
    if (!cap) return 0;
    return Math.min(100, Math.round((Number(b.spent_today_usd) / cap) * 100));
  });

  protected readonly monthlyPct = computed<number>(() => {
    const b = this.budget();
    if (!b) return 0;
    const cap = Number(b.monthly_cap_usd);
    if (!cap) return 0;
    return Math.min(100, Math.round((Number(b.spent_month_usd) / cap) * 100));
  });

  protected readonly showBudgetWarning = computed<boolean>(
    () => this.dailyPct() >= 80 || this.monthlyPct() >= 80,
  );

  constructor() {
    this._refresh();
    // Debounced budget-cap save — driven by any input on the form.
    this.budgetForm.valueChanges
      .pipe(debounceTime(600), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this._saveBudget());
  }

  private _refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.keys.set(rows),
        error: (err: HttpErrorResponse) =>
          this.loadError.set(extractApiError(err) ?? 'Could not load keys.'),
      });
    this.api
      .getBudget()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (b) => {
          this.budget.set(b);
          this.budgetForm.setValue(
            {
              daily_cap_usd: Number(b.daily_cap_usd),
              monthly_cap_usd: Number(b.monthly_cap_usd),
            },
            { emitEvent: false },
          );
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load budget.');
        },
      });
  }

  protected openAddModal(): void {
    this.rowError.set(null);
    this.addModalOpen.set(true);
  }

  protected onAdded(_row: AiProviderKey): void {
    this.addModalOpen.set(false);
    this._refresh();
  }

  protected onAddClosed(): void {
    this.addModalOpen.set(false);
  }

  protected testKey(key: AiProviderKey): void {
    this.testingId.set(key.id);
    this.rowError.set(null);
    this.api
      .test(key.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.testingId.set(null);
          this.keys.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        },
        error: (err: HttpErrorResponse) => {
          this.testingId.set(null);
          this.rowError.set({
            id: key.id,
            message: extractApiError(err) ?? 'Test failed.',
          });
        },
      });
  }

  protected deleteKey(key: AiProviderKey): void {
    const label = key.label ? `"${key.label}"` : `sk-…${key.last4}`;
    if (!confirm(`Delete ${label}? Any assistants using it will need to be re-linked.`)) return;
    this.deletingId.set(key.id);
    this.rowError.set(null);
    this.api
      .delete(key.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deletingId.set(null);
          this.keys.update((rows) => rows.filter((r) => r.id !== key.id));
        },
        error: (err: HttpErrorResponse) => {
          this.deletingId.set(null);
          if (err.status === 409) {
            const detail = (err.error?.detail ?? err.error) as
              | AiProviderKeyReferencedError
              | undefined;
            if (detail && detail.reason === 'referenced_by_assistants') {
              this.reassignTarget.set({ from: key, count: detail.reference_count });
              return;
            }
          }
          this.rowError.set({
            id: key.id,
            message: extractApiError(err) ?? 'Delete failed.',
          });
        },
      });
  }

  protected onReassigned(): void {
    this.reassignTarget.set(null);
    this._refresh();
  }

  protected onReassignClosed(): void {
    this.reassignTarget.set(null);
  }

  protected statusBadge(key: AiProviderKey): { label: string; cls: string; title: string | null } {
    switch (key.test_status) {
      case 'success':
        return {
          label: 'Working',
          cls: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
          title: key.test_last_at
            ? `Last tested: ${new Date(key.test_last_at).toLocaleString()}`
            : null,
        };
      case 'failed':
        return {
          label: 'Failed',
          cls: 'bg-red-500/10 text-red-300 ring-red-500/20',
          title: key.test_last_error ?? 'Test failed',
        };
      default:
        return {
          label: 'Untested',
          cls: 'bg-surface-2 text-muted ring-subtle',
          title: 'Click Test to verify the key works',
        };
    }
  }

  private _saveBudget(): void {
    if (this.budgetForm.invalid) return;
    this.budgetSaving.set(true);
    this.budgetError.set(null);
    const raw = this.budgetForm.getRawValue();
    this.api
      .updateBudget({
        daily_cap_usd: raw.daily_cap_usd,
        monthly_cap_usd: raw.monthly_cap_usd,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.budgetSaving.set(false);
          this.budget.set(updated);
          this.budgetSavedAt.set(Date.now());
        },
        error: (err: HttpErrorResponse) => {
          this.budgetSaving.set(false);
          this.budgetError.set(extractApiError(err) ?? 'Budget update failed.');
        },
      });
  }
}
