import { Component, input } from '@angular/core';
import { AbstractControl } from '@angular/forms';

const DEFAULT_MESSAGES: Record<string, string | ((err: any) => string)> = {
  required: 'This field is required',
  email: 'Please enter a valid email',
  minlength: (err) => `Must be at least ${err.requiredLength} characters`,
  maxlength: (err) => `Must be at most ${err.requiredLength} characters`,
  min: (err) => `Minimum value is ${err.min}`,
  max: (err) => `Maximum value is ${err.max}`,
  pattern: 'Invalid format',
  passwordMismatch: 'Passwords do not match',
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
