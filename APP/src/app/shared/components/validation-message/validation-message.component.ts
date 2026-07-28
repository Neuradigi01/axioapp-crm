import { Component, input } from '@angular/core';
import { AbstractControl } from '@angular/forms';

import { REASON } from '@shared/validators/custom-validators';

interface ValidatorErrorDetail {
  requiredLength?: number;
  min?: number;
  max?: number;
}

const DEFAULT_MESSAGES: Record<string, string | ((err: ValidatorErrorDetail) => string)> = {
  required: 'This field is required',
  email: 'Please enter a valid email',
  minlength: (err) => `Must be at least ${err.requiredLength} characters`,
  maxlength: (err) => `Must be at most ${err.requiredLength} characters`,
  min: (err) => `Minimum value is ${err.min}`,
  max: (err) => `Maximum value is ${err.max}`,
  pattern: 'Invalid format',
  passwordMismatch: 'Passwords do not match',
  // Keys emitted by the shared validators in `@shared/validators/custom-validators`.
  // Reason strings come from `REASON` so form errors and CSV `errors.csv` rows
  // read identically.
  nameInvalid: REASON.invalidName,
  emailInvalid: REASON.invalidEmail,
  phoneInvalid: REASON.invalidPhone,
  passwordWeak: REASON.weakPassword,
  urlInvalid: REASON.invalidUrl,
  invalidNumber: REASON.invalidNumber,
  outOfRange: (err) => {
    if (typeof err.min === 'number' && typeof err.max === 'number') {
      return `Value must be between ${err.min} and ${err.max}.`;
    }
    return REASON.outOfRange;
  },
  invalidDate: REASON.invalidDate,
  invalidDateTime: REASON.invalidDateTime,
  dateInPast: REASON.dateInPast,
};

@Component({
  selector: 'app-validation-message',
  standalone: true,
  templateUrl: './validation-message.component.html',
})
export class ValidationMessageComponent {
  control = input.required<AbstractControl>();
  label = input<string>('');
  errors = input<Record<string, string>>({});

  errorMessage(): string {
    const ctrl = this.control();
    if (!ctrl || !ctrl.errors || (!ctrl.touched && !ctrl.dirty)) {
      return '';
    }

    const customErrors = this.errors();
    const labelText = this.label();

    for (const key of Object.keys(ctrl.errors)) {
      if (customErrors[key]) {
        return customErrors[key];
      }

      if (key === 'required' && labelText) {
        return `${labelText} is required`;
      }

      const defaultMsg = DEFAULT_MESSAGES[key];
      if (defaultMsg) {
        return typeof defaultMsg === 'function' ? defaultMsg(ctrl.errors![key]) : defaultMsg;
      }

      return 'Invalid value';
    }

    return '';
  }
}
