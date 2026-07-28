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
  invalidNumber: 'value must be a number',
  outOfRange: 'value is outside the allowed range',
  invalidDate: 'date must be in YYYY-MM-DD format',
  invalidDateTime: 'date-time must be in ISO 8601 format',
  dateInPast: 'date cannot be in the past',
  dateTooOld: 'date is older than allowed',
  fileTooLarge: 'file exceeds the maximum size',
  unsupportedFileType: 'file type is not allowed',
  invalidChoice: 'value is not an allowed option',
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
 * Numeric-range validator for string-typed controls (HTML5 `<input type="number">`
 * feeds back a string). Empty short-circuits to `null` per the other
 * validators — combine with `Validators.required` when non-empty is
 * required. Emits `outOfRange` with the reason string, plus `min`/`max`
 * numeric fields for templates that want to show the bounds.
 */
export function numericInRange(min: number, max: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const raw = control.value;
    if (isEmpty(raw)) return null;
    const value = typeof raw === 'number' ? raw : Number(String(raw).trim());
    if (!Number.isFinite(value)) {
      return { invalidNumber: REASON.invalidNumber };
    }
    if (value < min || value > max) {
      return { outOfRange: REASON.outOfRange, min, max };
    }
    return null;
  };
}

/** YYYY-MM-DD. */
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Accepts YYYY-MM-DDTHH:mm(:ss)?(Z or ±HH:mm)? — HTML5 `datetime-local` and full ISO 8601. */
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/;

/**
 * `<input type="date">` value shape check. Empty → null.
 */
export function isoDateValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (!ISO_DATE_RE.test(value) || Number.isNaN(new Date(value).getTime())) {
    return { invalidDate: REASON.invalidDate };
  }
  return null;
}

/**
 * `<input type="datetime-local">` and ISO 8601. Empty → null.
 */
export function isoDateTimeValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (!ISO_DATETIME_RE.test(value) || Number.isNaN(new Date(value).getTime())) {
    return { invalidDateTime: REASON.invalidDateTime };
  }
  return null;
}

/**
 * Rejects ISO date / date-time values in the past. 5-minute grace covers
 * clock skew; date-only values are treated as "end of that day local"
 * so selecting today is always valid until midnight.
 */
export function dateNotPastValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null; // shape check belongs elsewhere
  const isDateOnly = value.length <= 10 && ISO_DATE_RE.test(value);
  const target = isDateOnly ? parsed.getTime() + 24 * 60 * 60 * 1000 : parsed.getTime();
  const graceMs = 5 * 60 * 1000;
  if (target + graceMs < Date.now()) {
    return { dateInPast: REASON.dateInPast };
  }
  return null;
}

/**
 * Rejects ISO date / date-time values earlier than `n` days ago. Used for
 * "log-after-the-fact" surfaces (call logs, historical activities) where
 * arbitrary-past is *bad* but a bounded past window is legitimate. Future
 * values pass — separate check with `dateNotPastValidator` if the field
 * must be forward-only.
 */
export function dateWithinPastDays(n: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const raw = control.value;
    if (isEmpty(raw)) return null;
    const parsed = new Date(String(raw).trim());
    if (Number.isNaN(parsed.getTime())) return null;
    const earliest = Date.now() - n * 24 * 60 * 60 * 1000;
    if (parsed.getTime() < earliest) {
      return { dateTooOld: REASON.dateTooOld, days: n };
    }
    return null;
  };
}

/**
 * `<input type="file">` control validator. Checks File.size and extension.
 * Empty short-circuits to `null`.
 */
export function fileUploadValidator(opts: { maxMb: number; exts: readonly string[] }): ValidatorFn {
  const allowedLower = opts.exts.map((e) => e.toLowerCase());
  const maxBytes = opts.maxMb * 1024 * 1024;
  return (control: AbstractControl): ValidationErrors | null => {
    const file = control.value as File | null | undefined;
    if (!file) return null;
    const dotName = file.name || '';
    const ext = ('.' + (dotName.split('.').pop() ?? '')).toLowerCase();
    if (!allowedLower.includes(ext)) {
      return { unsupportedFileType: REASON.unsupportedFileType, allowed: opts.exts };
    }
    if (file.size > maxBytes) {
      return { fileTooLarge: REASON.fileTooLarge, maxMb: opts.maxMb };
    }
    return null;
  };
}

/**
 * Required + rejects whitespace-only strings. Emits the same `required`
 * error key so existing template branches for `required` cover it — the
 * validator's only job is to make "   " fail the same way as "".
 */
export function trimmedRequired(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (raw === null || raw === undefined) return { required: true };
  if (typeof raw !== 'string') return null;
  return raw.trim().length === 0 ? { required: true } : null;
}

/**
 * Value must be one of the allowed options. Empty short-circuits to `null`
 * (compose with `Validators.required` when a choice is mandatory).
 */
export function picklistValidator(allowed: readonly (string | number)[]): ValidatorFn {
  const set = new Set<string | number>(allowed);
  return (control: AbstractControl): ValidationErrors | null => {
    const raw = control.value;
    if (isEmpty(raw)) return null;
    return set.has(raw) ? null : { invalidChoice: REASON.invalidChoice, allowed };
  };
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
