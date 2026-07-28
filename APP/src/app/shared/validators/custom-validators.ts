import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

/**
 * Human-readable reason strings shared between form errors and the
 * downloadable CSV `errors.csv` output for bulk imports. Kept in sync
 * (verbatim) with `api/src/app/shared/validators.py` so an operator
 * sees the same message whether a row fails at the form or in a CSV
 * import.
 */
export const REASON = {
  requiredMissing: 'required field missing',
  invalidEmail: 'invalid email format',
  invalidPhone: 'phone must be 8–15 digits (with optional country code)',
  invalidName: 'name contains disallowed characters',
  weakPassword: 'password must be 8–128 chars with upper, lower, digit, and special',
  invalidUrl: 'invalid URL',
} as const;

/**
 * Regex source strings. Exported so the backend regex-sync guard test
 * (`api/tests/shared/test_validators.py::test_frontend_backend_patterns_sync`)
 * can read and behaviourally compare them to the Python patterns.
 * Keep the character classes identical on both sides.
 */
export const NAME_RE_SRC = "^[A-Za-zÀ-ÿ' .\\-]{2,100}$";
export const EMAIL_RE_SRC = '^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$';
export const PHONE_RE_SRC = '^\\+?[0-9]{8,15}$';
export const URL_RE_SRC = '^https?://[^\\s]+$';

const NAME_RE = new RegExp(NAME_RE_SRC);
const EMAIL_RE = new RegExp(EMAIL_RE_SRC);
const PHONE_RE = new RegExp(PHONE_RE_SRC);
const URL_RE = new RegExp(URL_RE_SRC);

const EMAIL_MAX = 254;
const URL_MAX = 2048;
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 128;

/** Strip common phone separators so `(415) 555-0132` becomes `4155550132`. */
function stripPhoneSeparators(raw: string): string {
  return raw.replace(/[\s()-]/g, '');
}

/**
 * Empty controls short-circuit to `null`. Whether an empty value is
 * "invalid" belongs to `Validators.required`, not the format validators.
 */
function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '';
}

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

/**
 * Rejects names with digits, emoji, or symbols outside `.` `-` `'`.
 * Latin + accented Latin only for v1; broaden to `\p{L}` if the target
 * market expands.
 */
export function nameValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  return NAME_RE.test(value) ? null : { nameInvalid: REASON.invalidName };
}

/**
 * RFC-lite email check — must contain `@` and a `.` in the domain, no
 * spaces, max 254 chars. Deliberately looser than the full RFC 5322
 * grammar; matches what HubSpot / Salesforce accept.
 */
export function emailValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (value.length > EMAIL_MAX || !EMAIL_RE.test(value)) {
    return { emailInvalid: REASON.invalidEmail };
  }
  return null;
}

/**
 * E.164-compatible phone check. Strips spaces, `()`, and `-` first so
 * `+91 98765 43210` and `(415) 555-0132` both pass. Result must be an
 * optional `+` followed by 8–15 digits.
 */
export function phoneValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const stripped = stripPhoneSeparators(String(raw));
  return PHONE_RE.test(stripped) ? null : { phoneInvalid: REASON.invalidPhone };
}

/**
 * Password strength: 8–128 chars with at least one upper, lower, digit,
 * and special. Applied to *new* password creation (register / reset /
 * profile change) — never to login, so existing users are not locked
 * out on rule tightening.
 */
export function passwordStrengthValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw);
  if (
    value.length < PASSWORD_MIN ||
    value.length > PASSWORD_MAX ||
    !/[A-Z]/.test(value) ||
    !/[a-z]/.test(value) ||
    !/[0-9]/.test(value) ||
    !/[^A-Za-z0-9]/.test(value)
  ) {
    return { passwordWeak: REASON.weakPassword };
  }
  return null;
}

/**
 * URL check — `http(s)://…` only, max 2048 chars, non-empty host.
 */
export function urlValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (value.length > URL_MAX || !URL_RE.test(value)) {
    return { urlInvalid: REASON.invalidUrl };
  }
  try {
    const parsed = new URL(value);
    if (!parsed.host) return { urlInvalid: REASON.invalidUrl };
  } catch {
    return { urlInvalid: REASON.invalidUrl };
  }
  return null;
}
