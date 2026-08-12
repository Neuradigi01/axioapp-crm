import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { AbstractControl } from '@angular/forms';

/**
 * Renders a red required-field error message under a form input, but
 * only after the operator has interacted with the control (i.e. it is
 * `touched`) and it currently fails validation. Use across every
 * mandatory input in the app for consistent UX: the message stays
 * hidden on first render, appears the moment the user tabs / clicks
 * out of an empty required field, and disappears once they fix it.
 *
 * Usage:
 *   <input formControlName="name" />
 *   <crm-field-error [control]="form.controls.name" />
 *
 * With a custom message:
 *   <crm-field-error
 *     [control]="form.controls.email"
 *     message="Enter an email so we can reach you." />
 */
@Component({
  selector: 'crm-field-error',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (visible()) {
      <span class="mt-0.5 block text-[11px] text-red-500">
        {{ message() }}
      </span>
    }
  `,
})
export class FieldErrorComponent {
  readonly control = input.required<AbstractControl | null>();
  readonly message = input<string>('This field is required.');

  protected readonly visible = computed<boolean>(() => {
    const c = this.control();
    return !!c && c.touched && c.invalid;
  });
}
