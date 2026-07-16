import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { FieldDef } from './types';

/**
 * Renders a single field from a `FieldDef` against an Angular
 * `FormControl`. Type-specific markup lives in the template's
 * `@switch (def().field_type)` block; this class owns the bits the
 * template needs computed up front (input id, error text, choice list).
 *
 * The component is "dumb": it does not own the control, build validators,
 * or talk to the form. The parent `DynamicFormComponent` does all of
 * that. Keep it that way — it is what makes the renderer reusable for
 * one-off ad-hoc forms outside the dynamic-form host later.
 */
@Component({
  selector: 'app-field-renderer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './field-renderer.component.html',
})
export class FieldRendererComponent {
  readonly def = input.required<FieldDef>();
  readonly control = input.required<FormControl>();

  readonly choices = computed<string[]>(() => this.def().options?.choices ?? []);
  readonly inputId = computed(() => `field-${this.def().field_key}`);
  readonly errorId = computed(() => `${this.inputId()}-err`);

  readonly showError = computed(() => {
    const c = this.control();
    return c.invalid && (c.touched || c.dirty);
  });

  readonly errorMessage = computed<string | null>(() => {
    const c = this.control();
    const e = c.errors;
    if (!this.showError() || !e) return null;
    if (e['required']) return 'This field is required.';
    if (e['email']) return 'Enter a valid email address.';
    if (e['min']) return `Must be at least ${e['min'].min}.`;
    if (e['max']) return `Must be at most ${e['max'].max}.`;
    if (e['minlength']) {
      return `Must be at least ${e['minlength'].requiredLength} characters.`;
    }
    if (e['maxlength']) {
      return `Must be at most ${e['maxlength'].requiredLength} characters.`;
    }
    if (e['pattern']) return 'Invalid format.';
    return 'Invalid value.';
  });

  protected isChecked(choice: string): boolean {
    const v = this.control().value;
    return Array.isArray(v) && v.includes(choice);
  }

  protected onMultiselectToggle(choice: string, event: Event): void {
    const checkbox = event.target as HTMLInputElement;
    const c = this.control();
    const raw = c.value;
    const current: string[] = Array.isArray(raw) ? [...raw] : [];
    const idx = current.indexOf(choice);
    if (checkbox.checked && idx < 0) {
      current.push(choice);
    } else if (!checkbox.checked && idx >= 0) {
      current.splice(idx, 1);
    }
    c.setValue(current);
    c.markAsDirty();
    c.markAsTouched();
  }
}
