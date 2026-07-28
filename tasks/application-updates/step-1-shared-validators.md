# Step 1 — Shared validators (FE + BE foundation)

**Goal:** Extend the existing frontend `commonValidators` layer with industry-standard rules for name, email, phone, password strength, URL, and numeric ranges, and mirror them in a new `api/src/app/shared/validators.py` so every subsequent step (forms + CSV imports) validates against the same source of truth.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** Pending
**Depends on:** nothing. This step lands the foundation every other step in the track consumes.

---

## Scope

Three existing frontend files and two new backend files. Zero DB changes. Zero component-file edits — those come in Steps 2–7.

- **Frontend (extend, no new file):**
  - `app/src/app/shared/validators/custom-validators.ts` — app-wide validators used by *both* `features/accounts/` and `features/user/`. Today only exports `matchFieldValidator`. Extend with `nameValidator`, `emailValidator`, `phoneValidator`, `passwordStrengthValidator`, `urlValidator`.
  - `app/src/app/features/user/core/shared/validators/index.ts` — the user-app scoped `commonValidators` object. Re-export the app-wide validators through it so forms that already call `commonValidators.email` pick up the tightened rule with zero form-file changes.
  - `app/src/app/features/user/core/shared/dynamic-form/validators.ts` — the field-def → validator chain used by dynamic custom-field rendering. Route field-type `email` / `phone` / `name` through the new shared validators so custom-field inputs validate identically to standard ones.

- **Backend (create):**
  - `api/src/app/shared/validators.py` — pure functions mirroring the frontend regex. `validate_name(str) -> str`, `validate_email(str) -> str`, `validate_phone(str) -> str`, `validate_password_strength(str) -> None`, `validate_url(str) -> str`. Each returns the normalized value on success and raises `ValueError` with a human-readable reason on failure. No DB access.
  - `api/src/app/shared/import_errors.py` — shared helper for CSV-import error output. Exports `ImportError` dataclass (`row_number: int, column: str | None, value: str | None, reason: str`) and `write_errors_csv(headers: list[str], rows: list[dict], errors: list[ImportError]) -> bytes`. This is the single writer that Steps 8–10 use for `errors.csv` output.

## Ruleset (locked)

| Field | Regex / rule |
|---|---|
| **Name** | `^[A-Za-zÀ-ÿ' .\-]{2,100}$` — letters (incl. accented), spaces, `.` `-` `'`. Trimmed before check. |
| **Email** | RFC-lite: `^[^\s@]+@[^\s@]+\.[^\s@]+$`, max 254 chars, lowercased on save. |
| **Phone** | Strip `()`, `-`, and spaces first. Result must match `^\+?[0-9]{8,15}$`. |
| **Password** | Min 8, max 128. `.*[A-Z]` AND `.*[a-z]` AND `.*[0-9]` AND `.*[^A-Za-z0-9]`. |
| **URL** | `^https?://[^\s]+$`, max 2048, host non-empty. |

**Reason strings** (used by both form errors and CSV `errors.csv`):

- `"required field missing"`
- `"invalid email format"`
- `"phone must be 8–15 digits (with optional country code)"`
- `"name contains disallowed characters"`
- `"password must be 8–128 chars with upper, lower, digit, and special"`
- `"invalid URL"`
- `"value exceeds max length of N"`
- `"value below minimum of N"` / `"above maximum of N"`

These strings are exported as constants from both `validators.py` (backend) and `custom-validators.ts` (frontend) so error messages match exactly.

## Frontend shape

`app/src/app/shared/validators/custom-validators.ts`:

```ts
export const REASON = {
  requiredMissing: 'required field missing',
  invalidEmail: 'invalid email format',
  invalidPhone: 'phone must be 8–15 digits (with optional country code)',
  invalidName: 'name contains disallowed characters',
  weakPassword: 'password must be 8–128 chars with upper, lower, digit, and special',
  invalidUrl: 'invalid URL',
} as const;

export function nameValidator(control: AbstractControl): ValidationErrors | null { ... }
export function emailValidator(control: AbstractControl): ValidationErrors | null { ... }
export function phoneValidator(control: AbstractControl): ValidationErrors | null { ... }
export function passwordStrengthValidator(control: AbstractControl): ValidationErrors | null { ... }
export function urlValidator(control: AbstractControl): ValidationErrors | null { ... }
```

`app/src/app/features/user/core/shared/validators/index.ts`:

```ts
import { emailValidator, phoneValidator, nameValidator, ... } from 'src/app/shared/validators/custom-validators';

export const commonValidators = {
  required: Validators.required,
  email: emailValidator,       // replaces Validators.email; same call site
  phone: () => phoneValidator, // keep the factory shape existing forms use
  name: nameValidator,
  password: passwordStrengthValidator,
  url: urlValidator,
  maxLength: Validators.maxLength,
  minLength: Validators.minLength,
};
```

## Backend shape

`api/src/app/shared/validators.py`:

```python
import re

NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ' .\-]{2,100}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^\+?[0-9]{8,15}$")
URL_RE = re.compile(r"^https?://[^\s]+$")

class ValidationError(ValueError):
    def __init__(self, reason: str, value: str | None = None):
        self.reason = reason
        self.value = value
        super().__init__(reason)

def validate_name(value: str) -> str: ...
def validate_email(value: str) -> str: ...   # lowercased return
def validate_phone(value: str) -> str: ...   # stripped separators, E.164-ish return
def validate_password_strength(value: str) -> None: ...
def validate_url(value: str) -> str: ...
```

`api/src/app/shared/import_errors.py`:

```python
from dataclasses import dataclass
import csv, io

@dataclass
class ImportError:
    row_number: int
    column: str | None
    value: str | None
    reason: str

def write_errors_csv(
    original_headers: list[str],
    original_rows: list[dict],
    errors: list[ImportError],
) -> bytes:
    """Write a CSV with original columns + __row_number, __column, __value, __error_reason."""
    ...
```

## Files to touch

| File | Action |
|---|---|
| `app/src/app/shared/validators/custom-validators.ts` | modified — add 5 validators + REASON constants |
| `app/src/app/features/user/core/shared/validators/index.ts` | modified — re-export via `commonValidators` |
| `app/src/app/features/user/core/shared/dynamic-form/validators.ts` | modified — route field-type `email` / `phone` / `name` to shared validators |
| `api/src/app/shared/validators.py` | created |
| `api/src/app/shared/import_errors.py` | created |
| `api/tests/test_shared_validators.py` | created — unit tests for all 5 backend validators + happy/edge cases |
| `app/src/app/shared/validators/custom-validators.spec.ts` | created — unit tests for all 5 frontend validators (Karma/Jasmine) |

**~7 files.** Within the per-step rule.

## Tests

`api/tests/test_shared_validators.py`:

- `validate_name`: accepts `"Mary-Jane O'Neil Jr."`, `"李小明"` (fail — outside range, adjust or document), `"John"`, rejects `"😀"`, `"John123"`, `"J"` (too short), `"<script>"`.
- `validate_email`: accepts `"user@example.com"`, `"user+tag@ex.co"`, rejects `"test@"`, `"@example.com"`, `"no-at.com"`, `"a b@x.com"`. Lowercases on return.
- `validate_phone`: accepts `"9876543210"`, `"+91 98765 43210"`, `"+1 (415) 555-0132"`, rejects `"abc"`, `"1234567"` (too short), `"12345678901234567"` (too long). Returns stripped form.
- `validate_password_strength`: accepts `"Passw0rd!"`, rejects `"password"`, `"PASSWORD1!"` (no lower), `"passw0rd!"` (no upper), `"Password!"` (no digit), `"Password1"` (no special), `"Pw1!"` (too short).
- `validate_url`: accepts `"https://example.com"`, `"http://x.co/y?z=1"`, rejects `"example.com"`, `"ftp://x.co"`.

Frontend spec file covers the same matrix against the Angular `AbstractControl` shape.

## Regex-sync guard

A single test in `api/tests/test_shared_validators.py` reads the frontend `custom-validators.ts` file, extracts the regex literal strings, and asserts they match the backend `re.compile(...)` patterns character-for-character. This is the invariant that keeps the two sides from drifting.

## Smoke

```
docker exec crm_api-api-1 pytest tests/test_shared_validators.py -v
cd app && npx ng test --include='**/custom-validators.spec.ts' --watch=false
```

Manual browser smoke is not applicable — no forms yet call the new validators until Steps 2–7. This step is validated purely by unit tests and by opening a Node REPL / Python REPL to spot-check imports.

## Risks

- **Regex on names blocking legitimate scripts** — the chosen name regex covers Latin / accented Latin only. Names in Devanagari, Chinese, Arabic will fail. Documented; acceptable for v1 given the target market. A follow-up broadens to `\p{L}` if needed.
- **Password rule strictness** — some existing users may have passwords that don't meet the new rules. They are only enforced on **new** password creation (register / reset / accept-invite / profile-tab change-password) — existing hashed passwords remain valid on login. This is called out in Step 2.
- **Email regex too loose** — deliberately does not enforce full RFC 5322 (which is 6+ KB of grammar). The chosen shape covers 99.9% of legitimate emails and matches what HubSpot / Salesforce accept.

## Rollback

Delete the two new backend files, revert the three frontend files. No downstream code depends on them until Step 2 starts wiring them in.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. Foundation lives in `shared/`.
- ✅ Rule 2: No DB changes, no tables. N/A.
- ✅ Rule 3: Custom fields layered model actively strengthened — `dynamic-form/validators.ts` routes through the same validators, so a custom email field validates identically to a standard one.
- ✅ Rule 4: Dynamic-form rendering unchanged. This step just changes which validator chain gets attached.
- ✅ Rule 5: Sidebar registry unchanged.
- ✅ Rule 6: Permission registry unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 7 files, < 400 lines total.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: Production-ready. No TODOs. Regex-sync guard prevents future drift.
