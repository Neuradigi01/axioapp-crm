import { ValidatorFn, Validators } from '@angular/forms';

import type { StandardFieldRendered } from '../../standard-fields/types';

/**
 * Loosely-permissive phone pattern: optional leading `+`, then 7–20
 * characters of digits, spaces, dashes, or parentheses. Same regex
 * the dynamic-form renderer's `validatorsForField()` uses for
 * `field_type === 'phone'`, lifted here so standard / static
 * FormControls in entity modals get the same check.
 */
export const PHONE_RE = /^\+?[0-9\s()-]{7,20}$/;

/**
 * Cross-modal validator vocabulary. Wraps Angular's
 * `Validators.*` so every entity form modal imports validators from
 * one place — and the phone regex isn't redefined per modal.
 *
 * `commonValidators.email` and `commonValidators.required` are direct
 * references to the Angular validators (no closure, no wrapper) —
 * compositionally identical to using `Validators.email` /
 * `Validators.required` inline but with a uniform import path.
 *
 * `commonValidators.phone()` and `commonValidators.maxLength(n)` are
 * thin builders.
 */
export const commonValidators = {
  required: Validators.required as ValidatorFn,
  email: Validators.email as ValidatorFn,
  phone: (): ValidatorFn => Validators.pattern(PHONE_RE),
  maxLength: (n: number): ValidatorFn => Validators.maxLength(n),
  minLength: (n: number): ValidatorFn => Validators.minLength(n),
} as const;

/**
 * Append `Validators.required` to `base` iff the standard-field
 * override row marks the field required. Returns a new array — never
 * mutates `base`.
 *
 * Modals used to write this inline for every standard field:
 *
 *     const phoneRow = map['phone'];
 *     const phoneV: ValidatorFn[] = [Validators.maxLength(32)];
 *     if (phoneRow?.is_required) phoneV.push(Validators.required);
 *     this.standard.controls.phone.setValidators(phoneV);
 *
 * With this helper:
 *
 *     this.standard.controls.phone.setValidators(
 *       withRequiredIf([commonValidators.maxLength(32)], map['phone']),
 *     );
 *
 * Saves ~3 lines per field across N entity forms.
 */
export function withRequiredIf(
  base: ValidatorFn[],
  row: StandardFieldRendered | undefined,
): ValidatorFn[] {
  return row?.is_required ? [...base, commonValidators.required] : base;
}
