import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

/**
 * Validates that a control's value matches another control in the same FormGroup.
 * @param matchField The name of the control to compare against
 */
export function matchFieldValidator(matchField: string): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const matchControl = control.parent?.get(matchField);
    if (matchControl && control.value !== matchControl.value) {
      return { passwordMismatch: true };
    }
    return null;
  };
}
