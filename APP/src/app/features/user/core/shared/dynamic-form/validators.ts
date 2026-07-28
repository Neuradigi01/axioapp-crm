import { ValidatorFn, Validators } from '@angular/forms';

import { emailValidator, phoneValidator } from '../../../../../shared/validators/custom-validators';
import { FieldDef, FieldValue, ValidationRules } from './types';

/**
 * Translates a `FieldDef` into the Angular validator chain.
 *
 * Rules come from two places:
 *   1. `is_required` flag on the definition → `Validators.required`.
 *   2. The free-form `validation` JSON blob → individual `Validators.*`.
 *
 * Plus per-type defaults: `email` gets the shared `emailValidator`,
 * `phone` gets the shared `phoneValidator`. Both live in
 * `app/src/app/shared/validators/custom-validators.ts` so a custom
 * email / phone field validates identically to a standard one. Custom
 * `pattern` from `validation` is additive — both apply when both are set.
 */
export function validatorsForField(def: FieldDef): ValidatorFn[] {
  const validators: ValidatorFn[] = [];

  if (def.is_required) {
    // `requiredTrue` is the right call for boolean "must agree" checkboxes,
    // but our boolean field is "yes / no" — null/false stays valid unless
    // someone also adds the explicit `required` flag, in which case false
    // is acceptable too (the control simply needs a value). Plain
    // `required` matches that intent for every field type.
    validators.push(Validators.required);
  }

  const rules: ValidationRules = def.validation ?? {};
  if (typeof rules.min === 'number') {
    validators.push(Validators.min(rules.min));
  }
  if (typeof rules.max === 'number') {
    validators.push(Validators.max(rules.max));
  }
  if (typeof rules.minLength === 'number') {
    validators.push(Validators.minLength(rules.minLength));
  }
  if (typeof rules.maxLength === 'number') {
    validators.push(Validators.maxLength(rules.maxLength));
  }
  if (typeof rules.pattern === 'string' && rules.pattern.length > 0) {
    validators.push(Validators.pattern(rules.pattern));
  }

  if (def.field_type === 'email') {
    validators.push(emailValidator);
  }
  if (def.field_type === 'phone') {
    validators.push(phoneValidator);
  }

  return validators;
}

/**
 * Empty-but-valid starting value for each `field_type`. Mirrors what the
 * backend would store for a never-edited custom field.
 */
export function defaultValueForField(def: FieldDef): FieldValue {
  switch (def.field_type) {
    case 'multiselect':
      return [];
    case 'boolean':
      return false;
    case 'number':
    case 'currency':
      return null;
    default:
      return '';
  }
}
