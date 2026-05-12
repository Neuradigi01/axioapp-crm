import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { debounceTime, takeUntil } from 'rxjs/operators';

import { FieldRendererComponent } from './field-renderer.component';
import { FieldDef, FieldValue, FormValue } from './types';
import { defaultValueForField, validatorsForField } from './validators';

/**
 * Host component for a dynamically-built form. Given an array of
 * `FieldDef`s and an initial `value`, it constructs an Angular
 * `FormGroup`, renders one `<app-field-renderer>` per definition, and
 * pipes value + validity changes back to the parent.
 *
 * Contract:
 *   - `value` is read once whenever `fields` rebuilds the form. It is
 *     NOT live-bound after that point — the parent must use
 *     `valueChange` to track edits, not a two-way binding. (Re-binding
 *     `value` to the same content we just emitted would fight the user's
 *     in-progress typing.)
 *   - `valueChange` is debounced 50 ms to avoid hammering the parent
 *     while the user is mid-keystroke.
 *   - `validityChange` fires synchronously alongside each value emit and
 *     once on initial build, so a parent's submit button can disable
 *     itself before the user touches anything.
 *
 * The component is zoneless-friendly: change detection is OnPush, all
 * inputs are signal-based, and rxjs subscriptions are scoped to either
 * the rebuild lifecycle (`rebuild$`) or the component lifecycle
 * (`takeUntilDestroyed`).
 */
@Component({
  selector: 'app-dynamic-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, FieldRendererComponent],
  templateUrl: './dynamic-form.component.html',
})
export class DynamicFormComponent {
  private readonly destroyRef = inject(DestroyRef);

  readonly fields = input.required<FieldDef[]>();
  readonly value = input<FormValue>({});
  readonly loading = input<boolean>(false);

  readonly valueChange = output<FormValue>();
  readonly validityChange = output<boolean>();

  protected readonly form = signal<FormGroup>(new FormGroup({}));
  protected readonly skeletonRows = [0, 1, 2, 3] as const;

  private readonly rebuild$ = new Subject<void>();

  constructor() {
    effect(() => {
      const defs = this.fields();
      // `value` is intentionally read via `untracked` so subsequent
      // parent re-emits don't clobber in-flight user edits. See the
      // class docstring for the contract.
      const initial = untracked(() => this.value());
      this.rebuildForm(defs, initial);
    });
  }

  /** Used by the template's `[formControl]` binding to narrow the type. */
  protected control(key: string): FormControl<FieldValue> {
    return this.form().controls[key] as FormControl<FieldValue>;
  }

  private rebuildForm(defs: FieldDef[], initial: FormValue): void {
    this.rebuild$.next();

    const controls: Record<string, FormControl<FieldValue>> = {};
    for (const def of defs) {
      const seed = initial[def.field_key] ?? defaultValueForField(def);
      controls[def.field_key] = new FormControl<FieldValue>(seed, {
        nonNullable: false,
        validators: validatorsForField(def),
      }) as FormControl<FieldValue>;
    }
    const fg = new FormGroup(controls);
    this.form.set(fg);

    fg.valueChanges
      .pipe(
        debounceTime(50),
        takeUntil(this.rebuild$),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => {
        this.valueChange.emit(fg.getRawValue() as FormValue);
        this.validityChange.emit(fg.valid);
      });

    // Surface validity once on initial build so the parent's submit
    // button reflects "required field empty" before the user touches a
    // thing. updateValueAndValidity is needed because new controls
    // start as VALID even when `required` and seeded empty.
    fg.updateValueAndValidity({ emitEvent: false });
    this.validityChange.emit(fg.valid);
  }
}
