import {
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable } from 'rxjs';

import { FieldDef, FormValue } from '../dynamic-form/types';
import { StandardFieldsApiService } from '../../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../../standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../../standard-fields/types';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Abstract base for entity-create / -edit modals (contact, lead, task,
 * walk-in, appointment …). Consolidates the form-modal scaffolding
 * that every concrete modal used to redeclare:
 *
 *   - Submit state:        `_submitting / _submitError` signals + Input setters
 *   - Custom-fields load:  `fields / fieldsLoading / fieldsError` signals
 *                          + `ngOnInit` subscription
 *   - Custom-field values: `customValue / customValid` signals
 *   - Standard-field overrides:
 *                          `stdFields` signal + `refreshStdFields()` +
 *                          `stdField(key) / isHidden(key)` helpers +
 *                          reactive refetch on `stdSignals.changedAt()`
 *   - `cancel` Output
 *
 * What each subclass MUST provide:
 *   - `entityType: string`             — key for `stdApi.render(...)` and
 *                                        the dynamic-form endpoint
 *                                        (e.g. ``'contact'``).
 *   - `renderCustomFields$()`          — delegates to the entity's api
 *                                        service (e.g. ``this.api.renderFields()``).
 *   - `applyStandardValidators(map)`   — entity-specific validators
 *                                        layered on top of the form's
 *                                        static `Validators.email`/etc.
 *
 * What stays on each subclass:
 *   - The entity-typed `save: EventEmitter<...>`
 *   - The entity-typed `_entity` signal + `@Input() set <entity>(v)`
 *   - The `standard` FormGroup + `buildForm()` / `resetForm(entity)`
 *   - Domain-specific watchers (e.g. contact duplicate-check) +
 *     handlers (`submit()`, `onCancel()`).
 *
 * Subclasses inherit ``protected readonly`` signals and helpers — both
 * the subclass component and its template can read them directly.
 *
 * @example
 *   @Component({
 *     selector: 'app-contact-form-modal',
 *     standalone: true,
 *     ...,
 *   })
 *   export class ContactFormModalComponent extends BaseFormModalComponent {
 *     protected readonly entityType = 'contact';
 *     private readonly api = inject(ContactsApiService);
 *
 *     @Output() readonly save = new EventEmitter<{
 *       create?: ContactCreate; update?: ContactUpdate;
 *     }>();
 *
 *     protected renderCustomFields$() {
 *       return this.api.renderFields();
 *     }
 *
 *     protected applyStandardValidators(map): void {
 *       // contact-specific validator layering
 *     }
 *   }
 */
@Component({
  // Standalone abstract — never instantiated directly. The empty template
  // here is irrelevant; each subclass declares its own `templateUrl`.
  template: '',
  standalone: true,
})
export abstract class BaseFormModalComponent implements OnInit {
  protected readonly destroyRef = inject(DestroyRef);
  protected readonly stdApi = inject(StandardFieldsApiService);
  protected readonly stdSignals = inject(StandardFieldsSignalsService);

  /** Entity-type key — e.g. ``'contact'``, ``'lead'``. Used for
   * `stdApi.render(<this>)`. */
  protected abstract readonly entityType: string;

  // --- Shared submit state -----------------------------------------

  protected readonly _submitting = signal(false);
  protected readonly _submitError = signal<string | null>(null);

  readonly submitting$ = this._submitting.asReadonly();
  readonly submitError$ = this._submitError.asReadonly();

  @Input() set submitting(value: boolean) {
    this._submitting.set(value);
  }

  @Input() set submitError(value: string | null) {
    this._submitError.set(value);
  }

  @Output() readonly cancel = new EventEmitter<void>();

  // --- Custom-fields state -----------------------------------------

  protected readonly fields = signal<FieldDef[]>([]);
  protected readonly fieldsLoading = signal(true);
  protected readonly fieldsError = signal<string | null>(null);

  protected readonly customValue = signal<FormValue>({});
  protected readonly customValid = signal(true);

  // --- Standard-fields override state -------------------------------

  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>({});

  // --- Subclass hooks ----------------------------------------------

  /** Stream of custom-field definitions for ``entityType``. Subclasses
   * typically delegate to ``this.api.renderFields()``. */
  protected abstract renderCustomFields$(): Observable<FieldDef[]>;

  /** Layer override-driven validators (``Validators.required`` from the
   * registry override row) onto the subclass's static
   * (``Validators.email`` / ``Validators.maxLength``) validators. Called
   * after the override map is fetched. */
  protected abstract applyStandardValidators(map: Record<string, StandardFieldRendered>): void;

  // --- Lifecycle ---------------------------------------------------

  constructor() {
    // Refetch override-merged defs on Settings save/reset.
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
  }

  ngOnInit(): void {
    this.renderCustomFields$()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => {
          this.fields.set(defs);
          this.fieldsLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.fieldsError.set(extractApiError(err) ?? 'Could not load custom field definitions.');
          this.fieldsLoading.set(false);
        },
      });
  }

  // --- Standard-fields helpers --------------------------------------

  protected refreshStdFields(): void {
    this.stdApi.render(this.entityType).subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        // Modal still works with hardcoded fallbacks.
      },
    });
  }

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }
}
