import { ValidatorFn, Validators } from '@angular/forms';

import {
  choicesCsvValidator,
  currencyCodeValidator,
  dateFutureValidator,
  dateNotFutureValidator,
  dateNotPastValidator,
  dateWithinFutureDays,
  dateWithinPastDays,
  dateWithinPastHours,
  emailValidator,
  fileUploadValidator,
  gstinValidator,
  hostnameApexValidator,
  hostnameValidator,
  isoDateTimeValidator,
  isoDateValidator,
  localeValidator,
  maxDecimalsValidator,
  nameValidator,
  numericInRange,
  passwordStrengthValidator,
  phoneValidator,
  picklistValidator,
  postalCodeValidator,
  timezoneValidator,
  trimmedRequired,
  urlValidator,
  waVariablesValidator,
} from '../../../../../shared/validators/custom-validators';
import type { StandardFieldRendered } from '../../standard-fields/types';

/**
 * Legacy export kept for the two or three call sites that reference
 * `PHONE_RE` directly. New code should use `commonValidators.phone()`
 * so the format check lives in one place
 * (`app/src/app/shared/validators/custom-validators.ts`).
 *
 * Mirrors the backend rule in `src/app/shared/validators.py`: full
 * E.164 with a mandatory `+<country code>` prefix, then 7–14 digits
 * of subscriber number (15 max total after the `+`). Callers using
 * this direct regex must strip space/dash/paren separators from the
 * input first.
 */
export const PHONE_RE = /^\+[1-9][0-9]{7,14}$/;

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
  trimmedRequired: trimmedRequired as ValidatorFn,
  email: emailValidator as ValidatorFn,
  phone: (): ValidatorFn => phoneValidator,
  name: nameValidator as ValidatorFn,
  password: passwordStrengthValidator as ValidatorFn,
  url: urlValidator as ValidatorFn,
  maxLength: (n: number): ValidatorFn => Validators.maxLength(n),
  minLength: (n: number): ValidatorFn => Validators.minLength(n),
  numericInRange: (min: number, max: number): ValidatorFn => numericInRange(min, max),
  isoDate: isoDateValidator as ValidatorFn,
  isoDateTime: isoDateTimeValidator as ValidatorFn,
  dateNotPast: dateNotPastValidator as ValidatorFn,
  dateNotFuture: dateNotFutureValidator as ValidatorFn,
  dateFuture: dateFutureValidator as ValidatorFn,
  dateWithinPastDays: (n: number): ValidatorFn => dateWithinPastDays(n),
  dateWithinPastHours: (n: number): ValidatorFn => dateWithinPastHours(n),
  dateWithinFutureDays: (n: number): ValidatorFn => dateWithinFutureDays(n),
  fileUpload: (opts: { maxMb: number; exts: readonly string[] }): ValidatorFn =>
    fileUploadValidator(opts),
  picklist: (allowed: readonly (string | number)[]): ValidatorFn => picklistValidator(allowed),
  choicesCsv: choicesCsvValidator as ValidatorFn,
  waVariables: waVariablesValidator as ValidatorFn,
  hostname: hostnameValidator as ValidatorFn,
  hostnameApex: hostnameApexValidator as ValidatorFn,
  gstin: gstinValidator as ValidatorFn,
  currencyCode: currencyCodeValidator as ValidatorFn,
  timezone: timezoneValidator as ValidatorFn,
  locale: localeValidator as ValidatorFn,
  postalCode: postalCodeValidator as ValidatorFn,
  maxDecimals: (places: number): ValidatorFn => maxDecimalsValidator(places),
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
