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
  invalidPhone: 'phone must include country code (e.g. +919876543210)',
  invalidName: 'name contains disallowed characters',
  nameTooShort: 'name must be at least 2 characters',
  nameTooLong: 'name must be at most 100 characters',
  weakPassword: 'password must be 8–128 chars with upper, lower, digit, and special',
  invalidUrl: 'invalid URL',
  invalidNumber: 'value must be a number',
  outOfRange: 'value is outside the allowed range',
  invalidDate: 'date must be in YYYY-MM-DD format',
  invalidDateTime: 'date-time must be in ISO 8601 format',
  dateInPast: 'date cannot be in the past',
  dateMustBeFuture: 'date must be after today',
  dateInFuture: 'date cannot be in the future',
  dateTooOld: 'date is older than allowed',
  dateTooFarAhead: 'date is further ahead than allowed',
  fileTooLarge: 'file exceeds the maximum size',
  unsupportedFileType: 'file type is not allowed',
  invalidChoice: 'value is not an allowed option',
  invalidChoicesCsv: 'choices must be unique, ≤ 64 chars each, and no more than 100 total',
  invalidWaVariables:
    'variables must be numbered {{1}}, {{2}}, … sequentially without gaps (max 10)',
  invalidHostname: 'must be a valid hostname (e.g. example.com)',
  hostnameNotApex: 'enter the apex domain only (e.g. example.com, not mail.example.com)',
  invalidGstin:
    'GSTIN must be a 2-digit state code, 10-character PAN, then 3 characters (e.g. 29ABCDE1234F1Z5)',
  invalidCurrency: 'currency must be a 3-letter ISO code (e.g. INR)',
  invalidTimezone: 'timezone must be an IANA name (e.g. Asia/Kolkata)',
  invalidLocale: 'locale must look like en or en-IN',
  invalidPostalCode: 'postal code must be 3–10 letters, digits, spaces or dashes',
  tooManyDecimals: 'too many decimal places',
} as const;

/**
 * Regex source strings. Exported so the backend regex-sync guard test
 * (`api/tests/shared/test_validators.py::test_frontend_backend_patterns_sync`)
 * can read and behaviourally compare them to the Python patterns.
 * Keep the character classes identical on both sides.
 */
export const NAME_RE_SRC = "^[A-Za-zÀ-ÿ' .\\-]{2,100}$";
export const EMAIL_RE_SRC = '^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$';
export const PHONE_RE_SRC = '^\\+[1-9][0-9]{7,14}$';
export const URL_RE_SRC = '^https?://[^\\s]+$';
export const GSTIN_RE_SRC = '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$';
export const CURRENCY_RE_SRC = '^[A-Z]{3}$';
export const LOCALE_RE_SRC = '^[a-z]{2,3}(-[A-Z]{2})?$';
export const POSTAL_CODE_RE_SRC = '^[A-Za-z0-9][A-Za-z0-9 -]{1,8}[A-Za-z0-9]$';

const NAME_RE = new RegExp(NAME_RE_SRC);
// Character-class check only (no length bounds). Lets the validator
// distinguish "too short" from "bad characters" so the error message
// tells the operator the actual problem instead of always blaming the
// character set.
const NAME_CHARS_ONLY_RE = /^[A-Za-zÀ-ÿ' .-]*$/;
const EMAIL_RE = new RegExp(EMAIL_RE_SRC);
const PHONE_RE = new RegExp(PHONE_RE_SRC);
const URL_RE = new RegExp(URL_RE_SRC);

const EMAIL_MAX = 254;
const URL_MAX = 2048;
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 128;

/**
 * Strip visual separators (space, dash, parens) so a value like
 * `+91 98765-43210` normalises to `+919876543210` before regex match.
 * Mirror of the backend's `_PHONE_SEPARATORS_RE.sub("", value)` so a
 * paste from any source formats to the same canonical digits either
 * side of the wire.
 */
export function stripPhoneSeparators(raw: string): string {
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
 *
 * Returns a `nameInvalid` error keyed to the specific failure — length
 * vs. character-set — so the UI can render "must be at least 2
 * characters" for a 1-letter input instead of the misleading
 * "disallowed characters" (a single letter is a valid character but
 * fails the length bound).
 */
export function nameValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (NAME_RE.test(value)) return null;
  // Report the actual reason the composite regex failed.
  if (!NAME_CHARS_ONLY_RE.test(value)) {
    return { nameInvalid: REASON.invalidName };
  }
  if (value.length < 2) return { nameInvalid: REASON.nameTooShort };
  if (value.length > 100) return { nameInvalid: REASON.nameTooLong };
  return { nameInvalid: REASON.invalidName };
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
 * E.164 phone check with **mandatory country code**. Strips space /
 * dash / paren separators first (so `+91 98765-43210` is accepted),
 * then matches `^\+[1-9]\d{7,14}$`: a leading `+`, a non-zero
 * country-code digit, then 7–14 more digits (E.164 max is 15 digits
 * after the `+`). Mirrors the backend rule in
 * `src/app/shared/validators.py` so both sides accept the same
 * international format.
 *
 * Empty input short-circuits to `null`; `Validators.required` owns
 * the required-ness gate.
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
 * Rejects ISO date / date-time values in the future. Use for "actual"
 * events that have already happened (e.g. won-deal close date, purchase
 * date) — today counts as valid; tomorrow and later do not. Mirror of
 * `dateNotPastValidator`.
 */
export function dateNotFutureValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const isDateOnly = value.length <= 10 && ISO_DATE_RE.test(value);
  // For date-only, "target" is start of that day. For datetime, exact instant.
  const target = parsed.getTime();
  const graceMs = 5 * 60 * 1000;
  // A date-only value for today parses to 00:00 UTC — treat as valid until
  // end-of-tomorrow in local time (so "today" always passes).
  const now = Date.now();
  const endOfTodayLocal = new Date(new Date().setHours(23, 59, 59, 999)).getTime();
  const ceiling = isDateOnly ? endOfTodayLocal : now + graceMs;
  return target <= ceiling ? null : { dateInFuture: REASON.dateInFuture };
}

/**
 * Rejects ISO date / date-time values that are not strictly after today.
 * Use for "expected" fields (lead close date, walk-in return date) where
 * today doesn't make sense — if the target is today you'd just do it now
 * rather than set an expectation. For fields where today IS a valid pick
 * (task due, appointment slot), use `dateNotPastValidator` instead.
 *
 * Date-only strings (`YYYY-MM-DD`) compare against today's local date
 * string to avoid timezone drift. Datetime strings compare against the
 * start of tomorrow in local time.
 */
export function dateFutureValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (ISO_DATE_RE.test(value)) {
    const now = new Date();
    const todayStr =
      `${now.getFullYear()}-` +
      `${String(now.getMonth() + 1).padStart(2, '0')}-` +
      `${String(now.getDate()).padStart(2, '0')}`;
    return value > todayStr ? null : { dateMustBeFuture: REASON.dateMustBeFuture };
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null; // shape check belongs elsewhere
  const now = new Date();
  const startOfTomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime();
  return parsed.getTime() >= startOfTomorrow ? null : { dateMustBeFuture: REASON.dateMustBeFuture };
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
 * Rejects values more than `n` hours in the past. Same shape as
 * `dateWithinPastDays` but sub-day granularity — for queue / wait-time
 * fields where "yesterday" is already suspicious. Future values pass;
 * pair with `dateNotFutureValidator` for a full past-only window.
 */
export function dateWithinPastHours(n: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const raw = control.value;
    if (isEmpty(raw)) return null;
    const parsed = new Date(String(raw).trim());
    if (Number.isNaN(parsed.getTime())) return null;
    const earliest = Date.now() - n * 60 * 60 * 1000;
    if (parsed.getTime() < earliest) {
      return { dateTooOld: REASON.dateTooOld, hours: n };
    }
    return null;
  };
}

/**
 * Rejects values more than `n` days in the future. Mirror of
 * `dateWithinPastDays` for forward-looking fields (expected return
 * date, forecast close date) where a year-out cap is enough — anything
 * further is a typo (e.g. year 3025). Past values pass; pair with
 * `dateFutureValidator` for a strict tomorrow-onward window.
 */
export function dateWithinFutureDays(n: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const raw = control.value;
    if (isEmpty(raw)) return null;
    const parsed = new Date(String(raw).trim());
    if (Number.isNaN(parsed.getTime())) return null;
    const latest = Date.now() + n * 24 * 60 * 60 * 1000;
    if (parsed.getTime() > latest) {
      return { dateTooFarAhead: REASON.dateTooFarAhead, days: n };
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
 * CSV of custom-field choices. Rejects duplicates (case-insensitive after
 * trim), entries longer than 64 chars, and more than 100 entries. Empty
 * short-circuits to `null` — required-ness belongs to `Validators.required`.
 */
export function choicesCsvValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const parts = String(raw)
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (parts.length > 100) {
    return { invalidChoicesCsv: REASON.invalidChoicesCsv };
  }
  const seen = new Set<string>();
  for (const p of parts) {
    if (p.length > 64) return { invalidChoicesCsv: REASON.invalidChoicesCsv };
    const key = p.toLowerCase();
    if (seen.has(key)) return { invalidChoicesCsv: REASON.invalidChoicesCsv };
    seen.add(key);
  }
  return null;
}

/**
 * WhatsApp template body / header variable syntax: `{{n}}` placeholders
 * must start at 1, be sequential without gaps, and number no more than 10.
 * Text without any placeholder passes. Empty short-circuits to `null`.
 */
export function waVariablesValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const nums: number[] = [];
  const re = /\{\{\s*(\d+)\s*\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(String(raw))) !== null) {
    nums.push(Number(match[1]));
  }
  if (nums.length === 0) return null;
  const distinct = Array.from(new Set(nums)).sort((a, b) => a - b);
  if (distinct.length > 10) {
    return { invalidWaVariables: REASON.invalidWaVariables };
  }
  for (let i = 0; i < distinct.length; i++) {
    if (distinct[i] !== i + 1) {
      return { invalidWaVariables: REASON.invalidWaVariables };
    }
  }
  return null;
}

/** RFC-1123 hostname: 1–253 chars total; labels 1–63 alnum with internal hyphens; ≥ 2 labels. */
const HOSTNAME_RE =
  /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/i;

/**
 * Any RFC-1123 hostname (subdomains allowed). Empty short-circuits to `null`.
 * Case-insensitive on input; normalize case-side before persisting if you care.
 */
export function hostnameValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  return HOSTNAME_RE.test(value) ? null : { invalidHostname: REASON.invalidHostname };
}

/**
 * Apex-only hostname. Rejects anything with more than the effective TLD + 1
 * label (i.e. `example.com` OK, `mail.example.com` NOT OK, `example.co.uk`
 * OK — since `.co.uk` is a 2-part effective TLD). Uses a small hard-coded
 * multi-part-TLD list; extend as new cases surface.
 */
const MULTI_PART_TLDS = new Set<string>([
  'co.uk',
  'co.in',
  'com.au',
  'com.br',
  'co.jp',
  'co.kr',
  'co.nz',
  'com.mx',
  'com.sg',
]);

export function hostnameApexValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim().toLowerCase();
  if (!HOSTNAME_RE.test(value)) return { invalidHostname: REASON.invalidHostname };
  const parts = value.split('.');
  const tail2 = parts.slice(-2).join('.');
  const effectiveTldParts = MULTI_PART_TLDS.has(tail2) ? 2 : 1;
  // Apex = <one label>.<effective TLD>.
  if (parts.length !== effectiveTldParts + 1) {
    return { hostnameNotApex: REASON.hostnameNotApex };
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

const GSTIN_RE = new RegExp(GSTIN_RE_SRC);
const CURRENCY_RE = new RegExp(CURRENCY_RE_SRC);
const LOCALE_RE = new RegExp(LOCALE_RE_SRC);
const POSTAL_CODE_RE = new RegExp(POSTAL_CODE_RE_SRC);

/**
 * Indian GSTIN: 2-digit state code, 10-char PAN, entity digit, `Z`,
 * checksum char. Compared upper-cased so a pasted lowercase value is
 * accepted (the form upper-cases it on save).
 */
export function gstinValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  return GSTIN_RE.test(String(raw).trim().toUpperCase())
    ? null
    : { gstinInvalid: REASON.invalidGstin };
}

/** ISO 4217-shaped currency code — three letters, compared upper-cased. */
export function currencyCodeValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  return CURRENCY_RE.test(String(raw).trim().toUpperCase())
    ? null
    : { currencyInvalid: REASON.invalidCurrency };
}

/**
 * IANA timezone the browser's Intl database knows (e.g. `Asia/Kolkata`,
 * `UTC`). The backend checks the same value against Python's `zoneinfo`.
 */
export function timezoneValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  const value = String(raw).trim();
  if (!value.includes('/') && value !== 'UTC') {
    return { timezoneInvalid: REASON.invalidTimezone };
  }
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value });
    return null;
  } catch {
    return { timezoneInvalid: REASON.invalidTimezone };
  }
}

/** Language (+ optional region) locale tag: `en`, `hi`, `en-IN`. */
export function localeValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  return LOCALE_RE.test(String(raw).trim()) ? null : { localeInvalid: REASON.invalidLocale };
}

/** Postal / PIN / ZIP code: 3–10 letters or digits, inner spaces or dashes allowed. */
export function postalCodeValidator(control: AbstractControl): ValidationErrors | null {
  const raw = control.value;
  if (isEmpty(raw)) return null;
  return POSTAL_CODE_RE.test(String(raw).trim())
    ? null
    : { postalCodeInvalid: REASON.invalidPostalCode };
}

/** At most `places` digits after the decimal point. Empty → null. */
export function maxDecimalsValidator(places: number): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const raw = control.value;
    if (isEmpty(raw)) return null;
    const [, fraction = ''] = String(raw).trim().split('.');
    return fraction.length > places ? { tooManyDecimals: REASON.tooManyDecimals, places } : null;
  };
}
