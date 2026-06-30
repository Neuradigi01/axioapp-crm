/**
 * Sequence builder — used by both `/new` and `/:id/edit` routes.
 *
 * Layout:
 *   - Top: name input + active toggle + Save button.
 *   - Body: ordered step rows. Each row has a drag handle (HTML5 DnD,
 *     no library), a template-picker (typeahead against
 *     `EmailTemplatesApiService.list`), and a delay-days numeric input.
 *   - Bottom: "+ Add step" button.
 *
 * Drag-reorder:
 *   The drag handle uses native HTML5 DnD. On `dragstart` we stash the
 *   row index in a signal; on `drop` we splice the array. The step
 *   indices recompute from `index + 1` at save time (the API expects
 *   the array's order, not explicit step_order values).
 *
 * Save:
 *   `/new` POSTs `createSequence({name, is_active, steps})`. `/edit`
 *   PATCHes with the same shape — the backend rejects with 409 when
 *   active enrollments exist (the list page surfaces this; the form
 *   surfaces it inline).
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import {
  EmailSequencesApiService,
  SequenceStepCreate,
} from '../../services/email-sequences-api.service';
import {
  EmailTemplate,
  EmailTemplatesApiService,
} from '../../services/email-templates-api.service';

/** A row in the builder's signal-driven step list. `template_id` is
 *  the saved template's id; `template_name` mirrors the saved name
 *  for display only (avoids re-fetching per row when editing). */
interface BuilderStep {
  template_id: string | null;
  template_name: string | null;
  delay_days: number;
}

@Component({
  selector: 'app-sequence-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule, RouterLink],
  templateUrl: './sequence-builder.component.html',
})
export class SequenceBuilderComponent implements OnInit {
  private readonly api = inject(EmailSequencesApiService);
  private readonly templatesApi = inject(EmailTemplatesApiService);
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  /** Sequence id when editing; null for /new. */
  readonly sequenceId = input<string | null>(null);

  protected readonly isEdit = computed(() => this.sequenceId() !== null);

  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly submitting = signal<boolean>(false);
  protected readonly submitError = signal<string | null>(null);

  // --- Form --------------------------------------------------------

  protected readonly nameCtrl = this.fb.nonNullable.control('', [
    Validators.required,
    Validators.maxLength(255),
  ]);
  protected readonly activeCtrl = this.fb.nonNullable.control(true);

  /** Ordered step list. Signals so drag-reorder + add/remove trigger
   *  CD without manual nudges. */
  protected readonly steps = signal<BuilderStep[]>([]);

  protected readonly canSave = computed(() => {
    if (this.nameCtrl.invalid) return false;
    const rows = this.steps();
    if (rows.length === 0) return false;
    return rows.every((r) => r.template_id !== null && r.delay_days >= 0);
  });

  // --- Template picker state (per row) ----------------------------

  /** Currently-open template picker row index, or null. Only one row
   *  shows the picker at a time; clicking another row closes the
   *  prior one. */
  protected readonly pickerOpenRow = signal<number | null>(null);

  protected readonly templateResults = signal<EmailTemplate[]>([]);
  protected readonly templateSearchLoading = signal<boolean>(false);
  protected readonly templateSearchCtrl = new FormControl<string>('', {
    nonNullable: true,
  });

  // --- Drag state -------------------------------------------------

  protected readonly draggingIndex = signal<number | null>(null);
  protected readonly dropTargetIndex = signal<number | null>(null);

  ngOnInit(): void {
    const id = this.sequenceId();
    if (id !== null) this._loadSequence(id);

    this.templateSearchCtrl.valueChanges
      .pipe(debounceTime(250), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((q) => this._searchTemplates(q.trim()));
  }

  // --- Step list mutations ----------------------------------------

  addStep(): void {
    // Default new step: blank template + 2 days after prior step
    // (or 0 for the first step). Operator can change it inline.
    const current = this.steps();
    const defaultDelay = current.length === 0 ? 0 : 2;
    this.steps.update((rows) => [
      ...rows,
      {
        template_id: null,
        template_name: null,
        delay_days: defaultDelay,
      },
    ]);
  }

  removeStep(index: number): void {
    this.steps.update((rows) => rows.filter((_, i) => i !== index));
    if (this.pickerOpenRow() === index) this.pickerOpenRow.set(null);
  }

  setDelay(index: number, value: number): void {
    const safe = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
    this.steps.update((rows) => rows.map((r, i) => (i === index ? { ...r, delay_days: safe } : r)));
  }

  // --- Template picker --------------------------------------------

  openPicker(index: number): void {
    this.pickerOpenRow.set(index);
    this.templateSearchCtrl.setValue('');
    this._searchTemplates('');
  }

  closePicker(): void {
    this.pickerOpenRow.set(null);
  }

  selectTemplate(index: number, template: EmailTemplate): void {
    this.steps.update((rows) =>
      rows.map((r, i) =>
        i === index
          ? {
              ...r,
              template_id: template.id,
              template_name: template.name,
            }
          : r,
      ),
    );
    this.pickerOpenRow.set(null);
  }

  // --- Drag handlers ----------------------------------------------

  onDragStart(index: number, event: DragEvent): void {
    this.draggingIndex.set(index);
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      // Some browsers require a dataTransfer payload for the drag
      // to even start.
      event.dataTransfer.setData('text/plain', String(index));
    }
  }

  onDragOver(index: number, event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    if (this.draggingIndex() === null) return;
    if (this.dropTargetIndex() !== index) {
      this.dropTargetIndex.set(index);
    }
  }

  onDragLeave(): void {
    this.dropTargetIndex.set(null);
  }

  onDrop(index: number, event: DragEvent): void {
    event.preventDefault();
    const from = this.draggingIndex();
    if (from === null || from === index) {
      this.draggingIndex.set(null);
      this.dropTargetIndex.set(null);
      return;
    }
    this.steps.update((rows) => {
      const next = rows.slice();
      const [moved] = next.splice(from, 1);
      next.splice(index, 0, moved);
      return next;
    });
    this.draggingIndex.set(null);
    this.dropTargetIndex.set(null);
  }

  onDragEnd(): void {
    this.draggingIndex.set(null);
    this.dropTargetIndex.set(null);
  }

  // --- Save -------------------------------------------------------

  save(): void {
    if (!this.canSave() || this.submitting()) return;
    this.submitting.set(true);
    this.submitError.set(null);

    const payload: { name: string; is_active: boolean; steps: SequenceStepCreate[] } = {
      name: this.nameCtrl.value,
      is_active: this.activeCtrl.value,
      steps: this.steps().map((r) => ({
        delay_days: r.delay_days,
        template_id: r.template_id as string, // guarded by canSave
      })),
    };

    const id = this.sequenceId();
    const request$ =
      id === null ? this.api.createSequence(payload) : this.api.updateSequence(id, payload);

    request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (saved) => {
        this.submitting.set(false);
        this.router.navigate(['/user/settings/email-sequences', saved.id]);
      },
      error: (err: HttpErrorResponse) => {
        this.submitting.set(false);
        this.submitError.set(extractApiError(err));
      },
    });
  }

  // --- Loaders ----------------------------------------------------

  private _loadSequence(id: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getSequence(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.nameCtrl.setValue(row.name);
          this.activeCtrl.setValue(row.is_active);
          // Translate the saved step rows into BuilderSteps. We fetch
          // the matching template name in a single bulk call so the
          // builder doesn't render bare uuids.
          const templateIds = Array.from(new Set(row.steps.map((s) => s.template_id)));
          this.steps.set(
            row.steps
              .slice()
              .sort((a, b) => a.step_order - b.step_order)
              .map((s) => ({
                template_id: s.template_id,
                template_name: null,
                delay_days: s.delay_days,
              })),
          );
          this.loading.set(false);
          this._resolveTemplateNames(templateIds);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }

  private _resolveTemplateNames(ids: string[]): void {
    if (ids.length === 0) return;
    // One template GET per id — bounded by typical sequence size.
    for (const id of ids) {
      this.templatesApi
        .get(id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (t) => {
            this.steps.update((rows) =>
              rows.map((r) => (r.template_id === id ? { ...r, template_name: t.name } : r)),
            );
          },
          error: () => {
            // Soft-deleted template — leave the name null; the UI
            // will warn the operator to pick a fresh one.
          },
        });
    }
  }

  private _searchTemplates(q: string): void {
    this.templateSearchLoading.set(true);
    this.templatesApi
      .list({ q: q || undefined, is_active: true, size: 30 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.templateResults.set(resp.items);
          this.templateSearchLoading.set(false);
        },
        error: () => {
          this.templateSearchLoading.set(false);
        },
      });
  }
}
