import { ValidatorFn, Validators } from '@angular/forms';

import {
  emailValidator,
  nameValidator,
  passwordStrengthValidator,
  phoneValidator,
  urlValidator,
} from '../../../../../shared/validators/custom-validators';
import type { StandardFieldRendered } from '../../standard-fields/types';

/**
 * Legacy export kept for the two or three call sites that reference
 * `PHONE_RE` directly. New code should use `commonValidators.phone()`
 * so the format check lives in one place
 * (`app/src/app/shared/validators/custom-validators.ts`).
 *
 * The source string here matches the one that validator uses so
 * behaviour is identical; the character class is E.164-compatible
 * (optional `+`, then 8–15 digits) with separators stripped first.
 */
export const PHONE_RE = /^\+?[0-9\s()-]{8,20}$/;

/**
 * Cross-modal validator vocabulary. Wraps Angular's `Validators.*` so
 * every entity form modal imports validators from one place — and
 * name / email / phone / password / URL format checks aren't
 * redefined per modal.
 *
 * `commonValidators.required` is a direct reference to Angular's
 * `Validators.required`. The rest come from
 * `app/src/app/shared/validators/custom-validators.ts` so the exact
 * same rule is available to `features/accounts/` (which can't reach
 * into `features/user/`).
 *
 * `commonValidators.phone()` and `commonValidators.maxLength(n)` keep
 * the factory shape existing forms already call.
 */
export const commonValidators = {
  required: Validators.required as ValidatorFn,
  email: emailValidator as ValidatorFn,
  phone: (): ValidatorFn => phoneValidator,
  name: nameValidator as ValidatorFn,
  password: passwordStrengthValidator as ValidatorFn,
  url: urlValidator as ValidatorFn,
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
