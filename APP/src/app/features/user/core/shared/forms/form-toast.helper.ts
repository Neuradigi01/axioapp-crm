import { Injectable, inject } from '@angular/core';

import { ToastService } from '../../../../../shared/components/toast/toast.service';

/**
 * Standardised toast messages for form-submit validation failures.
 *
 * Every create/edit form in the app (leads, appointments, tasks,
 * catalog, properties, walk-ins, calls) fires the same toast when a
 * required field is missing or invalid, so operators always see the
 * same wording regardless of which entity they were editing. Changing
 * the copy here fans out everywhere — do not inline the message inside
 * individual form components.
 */
@Injectable({ providedIn: 'root' })
export class FormToastHelper {
  private readonly toast = inject(ToastService);

  /** Fired when submit is blocked by an invalid or missing required
   *  field. Callers pair this with the form's existing inline error so
   *  both channels announce the same failure — the toast reaches
   *  operators who scrolled past the inline banner. */
  requiredFieldsMissing(subtitle?: string): void {
    this.toast.warn('Please fill all required fields', {
      subtitle: subtitle ?? 'Some fields need attention before we can save.',
    });
  }

  /** Fired when submit is blocked by fields that are filled in but
   *  malformed (bad email, phone, URL, …). `labels` names the fields
   *  so the operator knows where to look without scrolling. */
  invalidFields(labels: readonly string[]): void {
    this.toast.warn('Please fix the highlighted fields', {
      subtitle: labels.length ? `Check: ${labels.join(', ')}.` : undefined,
    });
  }
}
