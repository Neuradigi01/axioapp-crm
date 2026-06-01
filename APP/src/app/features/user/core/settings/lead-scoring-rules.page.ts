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
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { AdvancedFilterModalComponent } from '../leads/advanced-filter-modal.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { extractApiError } from '@core/services/api-error.util';
import { FieldDef } from '../shared/dynamic-form/types';
import { FilterDsl, isEmptyFilter } from '../shared/filter-dsl.types';
import {
  LeadScoringRule,
  LeadScoringRuleCreate,
  LeadScoringRuleUpdate,
  LeadsApiService,
} from '../leads/leads-api.service';

/** Edit-modal state. `undefined` = "creating new"; `LeadScoringRule` =
 * "editing existing"; `null` = closed. */
type EditingState = LeadScoringRule | undefined | null;

@Component({
  selector: 'app-lead-scoring-rules-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    LucideAngularModule,
    AdvancedFilterModalComponent,
    ConfirmDialogComponent,
  ],
  template: `
    <div class="mx-auto max-w-5xl p-6 space-y-5">
      <header class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-lg font-semibold text-zinc-900">Lead scoring rules</h1>
          <p class="mt-0.5 text-xs text-zinc-500">
            Points add up across active rules; the final score is capped at 100 per lead.
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            (click)="onRecompute()"
            [disabled]="recomputing()"
            class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            @if (recomputing()) {
              <lucide-icon name="loader-2" class="h-4 w-4 animate-spin" />
              Recomputing…
            } @else {
              <lucide-icon name="refresh-cw" class="h-4 w-4" />
              Recompute scores now
            }
          </button>
          <button
            type="button"
            (click)="openCreate()"
            class="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-800"
          >
            <lucide-icon name="plus" class="h-4 w-4" />
            Add rule
          </button>
        </div>
      </header>

      @if (recomputeMessage(); as msg) {
        <p class="rounded-md bg-emerald-50 px-4 py-2 text-xs text-emerald-700 ring-1 ring-emerald-200">
          {{ msg }}
        </p>
      }
      @if (loadError(); as err) {
        <p class="rounded-md bg-red-50 px-4 py-2 text-xs text-red-700 ring-1 ring-red-200">
          {{ err }}
        </p>
      }

      <div class="overflow-hidden rounded-lg ring-1 ring-zinc-200 bg-white">
        <table class="min-w-full divide-y divide-zinc-200">
          <thead class="bg-zinc-50 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th class="px-4 py-2.5 text-left font-medium">Name</th>
              <th class="px-4 py-2.5 text-left font-medium">Condition</th>
              <th class="px-4 py-2.5 text-right font-medium">Points</th>
              <th class="px-4 py-2.5 text-center font-medium">Active</th>
              <th class="px-4 py-2.5 text-right font-medium">
                <span class="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-100 text-sm">
            @if (loading()) {
              <tr>
                <td colspan="5" class="px-4 py-6 text-center text-xs text-zinc-500">
                  Loading…
                </td>
              </tr>
            } @else {
              @for (rule of rules(); track rule.id) {
                <tr>
                  <td class="px-4 py-2.5 align-top font-medium text-zinc-900">
                    {{ rule.name }}
                  </td>
                  <td class="px-4 py-2.5 align-top text-xs text-zinc-600">
                    {{ humanizeCondition(rule.condition) }}
                  </td>
                  <td class="px-4 py-2.5 align-top text-right tabular-nums text-zinc-900">
                    {{ rule.points > 0 ? '+' + rule.points : rule.points }}
                  </td>
                  <td class="px-4 py-2.5 align-top text-center">
                    @if (rule.active) {
                      <span
                        class="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800 ring-1 ring-emerald-200"
                      >
                        Active
                      </span>
                    } @else {
                      <span
                        class="inline-flex items-center rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium text-zinc-700 ring-1 ring-zinc-200"
                      >
                        Inactive
                      </span>
                    }
                  </td>
                  <td class="px-4 py-2.5 align-top text-right">
                    <div class="inline-flex gap-1">
                      <button
                        type="button"
                        (click)="openEdit(rule)"
                        class="inline-flex items-center rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700"
                        aria-label="Edit rule"
                      >
                        <lucide-icon name="pencil" class="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        (click)="openDelete(rule)"
                        class="inline-flex items-center rounded-md p-1.5 text-red-500 hover:bg-red-50 hover:text-red-700"
                        aria-label="Delete rule"
                      >
                        <lucide-icon name="trash-2" class="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              } @empty {
                <tr>
                  <td colspan="5" class="px-4 py-10 text-center text-xs text-zinc-500">
                    No scoring rules yet. Add one to start scoring leads automatically.
                  </td>
                </tr>
              }
            }
          </tbody>
        </table>
      </div>
    </div>

    <!-- Edit / create rule modal. -->
    @if (editing() !== null) {
      <div
        class="fixed inset-0 z-40 flex items-center justify-center bg-zinc-900/40 px-4"
        role="dialog"
        aria-modal="true"
      >
        <div class="w-full max-w-md rounded-lg bg-white p-5 shadow-xl ring-1 ring-zinc-200">
          <h2 class="text-base font-semibold text-zinc-900">
            {{ editing() ? 'Edit rule' : 'New rule' }}
          </h2>
          <div class="mt-4 space-y-3">
            <label class="block">
              <span class="text-xs font-medium text-zinc-700">Name</span>
              <input
                type="text"
                maxlength="120"
                [(ngModel)]="formName"
                placeholder="e.g. Qualified + Mumbai"
                class="mt-1 block w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 shadow-sm focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              />
            </label>
            <label class="block">
              <span class="text-xs font-medium text-zinc-700">Points</span>
              <input
                type="number"
                min="-100"
                max="100"
                step="1"
                [(ngModel)]="formPoints"
                class="mt-1 block w-32 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 tabular-nums shadow-sm focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500"
              />
              <span class="ml-2 text-xs text-zinc-500">Range: -100 to 100</span>
            </label>
            <div>
              <span class="text-xs font-medium text-zinc-700">Condition</span>
              <div class="mt-1 flex items-center gap-2">
                <span class="flex-1 truncate rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-700">
                  {{ humanizeCondition(formCondition()) }}
                </span>
                <button
                  type="button"
                  (click)="openConditionPicker()"
                  class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
                >
                  <lucide-icon name="sliders-horizontal" class="h-3.5 w-3.5" />
                  Edit
                </button>
              </div>
            </div>
            <label class="flex items-center gap-2 text-xs text-zinc-700">
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-500"
                [(ngModel)]="formActive"
              />
              Active
            </label>
          </div>
          @if (formError(); as err) {
            <p class="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 ring-1 ring-red-200">
              {{ err }}
            </p>
          }
          <div class="mt-5 flex justify-end gap-2">
            <button
              type="button"
              (click)="closeEditor()"
              [disabled]="submitting()"
              class="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="button"
              (click)="submitEditor()"
              [disabled]="submitting()"
              class="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              @if (submitting()) {
                <lucide-icon name="loader-2" class="h-3.5 w-3.5 animate-spin" />
                Saving…
              } @else {
                Save
              }
            </button>
          </div>
        </div>
      </div>
    }

    <!-- Condition picker reuses the leads advanced-filter modal so the
         UI stays identical to "Advanced filter" on the leads list. -->
    @if (conditionPickerOpen()) {
      <app-advanced-filter-modal
        [initial]="formCondition()"
        [customFields]="customFields()"
        (apply)="onConditionApply($event)"
        (cancel)="closeConditionPicker()"
      />
    }

    <!-- Delete confirm. -->
    @if (deletingRule(); as rule) {
      <app-confirm-dialog
        [title]="'Delete rule “' + rule.name + '”?'"
        [body]="'Existing lead scores will be recomputed without this rule.'"
        [confirmLabel]="'Delete'"
        [danger]="true"
        [submitting]="deleting()"
        (confirm)="confirmDelete()"
        (cancel)="cancelDelete()"
      />
    }
  `,
})
export class LeadScoringRulesPage {
  private readonly api = inject(LeadsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly rules = signal<LeadScoringRule[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);

  readonly recomputing = signal(false);
  readonly recomputeMessage = signal<string | null>(null);

  readonly editing = signal<EditingState>(null);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  // Form fields — two-way bound to inputs.
  formName = '';
  formPoints = 10;
  formActive = true;
  readonly formCondition = signal<FilterDsl>({});

  readonly conditionPickerOpen = signal(false);
  readonly customFields = signal<FieldDef[]>([]);

  readonly deletingRule = signal<LeadScoringRule | null>(null);
  readonly deleting = signal(false);

  /** Memoised so the template doesn't recompute on every change-detection
   * pass (`humanizeCondition` is called per row + once for the form). */
  readonly humanizeCondition = (dsl: FilterDsl | null | undefined): string => {
    if (!dsl || isEmptyFilter(dsl)) return 'Matches every lead';
    const clauses = [...(dsl.all ?? []), ...(dsl.any ?? [])];
    return clauses
      .map((c) => `${c.field} ${c.op}${c.value !== undefined ? ' ' + JSON.stringify(c.value) : ''}`)
      .join(dsl.any?.length ? ' OR ' : ' AND ');
  };

  constructor() {
    this.reload();
    this.loadCustomFields();
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listScoringRules()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rules) => {
          this.rules.set(rules);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load scoring rules.',
          );
        },
      });
  }

  private loadCustomFields(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (fields) => this.customFields.set(fields),
        error: () => this.customFields.set([]),
      });
  }

  protected openCreate(): void {
    this.editing.set(undefined);
    this.formName = '';
    this.formPoints = 10;
    this.formActive = true;
    this.formCondition.set({});
    this.formError.set(null);
  }

  protected openEdit(rule: LeadScoringRule): void {
    this.editing.set(rule);
    this.formName = rule.name;
    this.formPoints = rule.points;
    this.formActive = rule.active;
    this.formCondition.set(rule.condition ?? {});
    this.formError.set(null);
  }

  protected closeEditor(): void {
    this.editing.set(null);
    this.submitting.set(false);
    this.formError.set(null);
  }

  protected openConditionPicker(): void {
    this.conditionPickerOpen.set(true);
  }

  protected closeConditionPicker(): void {
    this.conditionPickerOpen.set(false);
  }

  protected onConditionApply(dsl: FilterDsl): void {
    this.formCondition.set(dsl);
    this.conditionPickerOpen.set(false);
  }

  protected submitEditor(): void {
    const name = this.formName.trim();
    const points = Number(this.formPoints);
    if (!name) {
      this.formError.set('Please enter a name.');
      return;
    }
    if (!Number.isFinite(points) || points < -100 || points > 100) {
      this.formError.set('Points must be between -100 and 100.');
      return;
    }
    if (isEmptyFilter(this.formCondition())) {
      this.formError.set('Add at least one condition clause.');
      return;
    }
    const current = this.editing();
    this.submitting.set(true);
    this.formError.set(null);
    if (current) {
      const payload: LeadScoringRuleUpdate = {
        name,
        points,
        active: this.formActive,
        condition: this.formCondition(),
      };
      this.api
        .updateScoringRule(current.id, payload)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (updated) => {
            this.rules.update((rows) =>
              rows.map((r) => (r.id === updated.id ? updated : r)),
            );
            this.closeEditor();
            this.kickRecompute();
          },
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.formError.set(
              extractApiError(err) ?? 'Could not save rule.',
            );
          },
        });
    } else {
      const payload: LeadScoringRuleCreate = {
        name,
        points,
        active: this.formActive,
        condition: this.formCondition(),
      };
      this.api
        .createScoringRule(payload)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (created) => {
            this.rules.update((rows) => [...rows, created]);
            this.closeEditor();
            this.kickRecompute();
          },
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.formError.set(
              extractApiError(err) ?? 'Could not save rule.',
            );
          },
        });
    }
  }

  protected openDelete(rule: LeadScoringRule): void {
    this.deletingRule.set(rule);
  }

  protected cancelDelete(): void {
    this.deletingRule.set(null);
    this.deleting.set(false);
  }

  protected confirmDelete(): void {
    const rule = this.deletingRule();
    if (!rule) return;
    this.deleting.set(true);
    this.api
      .deleteScoringRule(rule.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.rules.update((rows) => rows.filter((r) => r.id !== rule.id));
          this.cancelDelete();
          this.kickRecompute();
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not delete rule.',
          );
        },
      });
  }

  protected onRecompute(): void {
    this.recomputing.set(true);
    this.recomputeMessage.set(null);
    this.api
      .recomputeScores()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.recomputing.set(false);
          this.recomputeMessage.set(
            `Recompute complete — ${resp.touched} lead score${resp.touched === 1 ? '' : 's'} updated.`,
          );
        },
        error: (err: HttpErrorResponse) => {
          this.recomputing.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not recompute scores.',
          );
        },
      });
  }

  /** Fire-and-forget recompute after every mutation so the leads list
   * shows the updated score next time it's loaded. Errors are swallowed
   * — the hourly Celery beat catches up if this fails. */
  private kickRecompute(): void {
    this.api
      .recomputeScores()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ error: () => undefined });
  }
}
