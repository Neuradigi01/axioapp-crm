# Application Updates — Form & CSV-Import Validation

A focused track that raises **every form** and **every bulk-import surface** in the app to industry-standard input validation. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready, closes a visible correctness gap that spans ~60 forms and 3 import flows.

## Why this exists

The app already ships with a small shared validator layer (`matchFieldValidator`, `commonValidators.phone`, `commonValidators.email`, `withRequiredIf`) but it is **inconsistently applied**. An audit of the frontend surfaced the following gaps:

| Field type | Gap today |
|---|---|
| **Name** (first / last / full / title) | No pattern anywhere — accepts digits, emoji, `<script>`, symbols. Only max-length in a subset of forms. |
| **Email** | Uses Angular's built-in `Validators.email` (too loose — accepts `test@`). Inconsistent max-length. |
| **Phone** | `commonValidators.phone` exists but almost no form calls it. No E.164 shape. |
| **Password** | Min 8 chars only. No uppercase / digit / special-char rule. `confirm_password` sometimes matched in code instead of via a validator. |
| **Numeric** | No min/max on `party_size`, `duration_min`, `smtp_port`, `budget`, `price`, `cost_price`. |
| **Dates** | No past-date block on future-only fields. No cross-field `start ≤ end`. |
| **URL / hostname / hex** | No validators exist. |
| **File uploads** | Only the call-recording modal validates size + extension. |
| **CSV imports** | Contacts / Leads / Catalog imports don't validate email / phone / name shape before writing rows. Contacts + Catalog have no downloadable errors CSV; Leads has `errors.csv` / `skipped.csv` / `warnings.csv` but its rules are shallow (just "required present" + "not a duplicate"). |

The result: a row like `full_name = "😀😀😀", phone = "abc", email = "test@"` currently sails through the entire pipeline — form, API, DB — and lands in the CRM as a garbage contact.

## What "industry standard" means for this track

Locked before implementation begins. These are the rules every form and import row is checked against:

| Field | Rule |
|---|---|
| **Name** | Letters + spaces + `.` `-` `'` only. 2–100 chars. No digits, emoji, symbols. Trimmed. |
| **Email** | Must contain `@` and a `.` in the domain. No spaces. Max 254. Lowercased on save. |
| **Phone** | E.164 compatible — optional `+`, then 8–15 digits. `()`, `-`, spaces allowed as separators but stripped for storage. 10-digit Indian numbers pass without `+`. |
| **Password** | Min 8, max 128. At least 1 upper, 1 lower, 1 digit, 1 special. `confirm_password` matches via a `matchFieldValidator`, not manual code. |
| **URL** | `http(s)://…` only, valid host, max 2048. |
| **Numeric** | Per-field min/max range. Positive where semantically required. Currency max 2 decimals. |
| **Date / datetime** | ISO shape. Future-only fields reject past. Cross-field `end ≥ start`. |
| **Text / notes / description** | Per-field max length (255 short, 2000 long, 4000 notes). Trimmed. |
| **Select / picklist** | Value must be in the server-provided options. |
| **File upload** | Whitelist extension + MIME + size cap per surface. |

## Acceptance criteria

Track is done when:

1. A single call site — `commonValidators.<rule>` on the frontend, `validators.<rule>()` on the backend — is used **everywhere** for the field types above.
2. Every one of the ~60 form components in the app applies the correct validator to each of its fields. The user sees an inline error the moment they type an invalid value; the submit button is disabled until the form is valid.
3. All three CSV imports (**contacts, leads, catalog**) validate every row against the same rules **before** writing it. Rows that fail land in a downloadable `errors.csv` with:
   - `__row_number` — 1-based data-row index in the original file.
   - `__column` — which column raised the failure.
   - `__value` — the offending value (echoed back so the user can see it).
   - `__error_reason` — a human-readable string, e.g. `"invalid email format"`, `"phone must be 8–15 digits"`, `"name contains disallowed characters"`, `"required field missing"`, `"duplicate in file"`.
4. Contacts and Catalog gain the same `errors.csv` download endpoint that Leads already has.
5. All validation runs from a **single source of truth** on the backend (`api/src/app/shared/validators.py`) so form / API / CSV rules can never drift.

## What this does NOT do

- Does not change the layered architecture (Router → Service → DAL). New shared validators live in `api/src/app/shared/`, which is where cross-cutting utilities already live (config, db, exceptions, storage).
- Does not add new form fields. Only adds validators to fields that already exist.
- Does not touch `features/admin/` (legacy template — untouched per `CLAUDE.md`).
- Does not add async validators (uniqueness checks against the API). Uniqueness is still checked server-side.
- Does not add password-strength meter UI (only the rule check). Meter is a Phase-5 UX polish.
- Does not add malware scanning or virus checks on file uploads.
- Does not change any DB schema. Zero migrations.
- Does not touch the workflow-canvas editor forms' *business logic* — only their input validation.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Shared validators (FE + BE foundation)](step-1-shared-validators.md) | COMPLETED | ~½ day |
| 2 | [Auth pages (accounts/)](step-2-auth-pages.md) | COMPLETED | ~½ day |
| 3 | [Core entity forms (contacts, leads, walk-ins)](step-3-core-entity-forms.md) | COMPLETED | ~½ day |
| 4 | [Activity & action forms (tasks, appointments, calls, reviews, notes)](step-4-activity-forms.md) | COMPLETED | ~½ day |
| 5 | [Config forms A — custom fields + templates](step-5-config-forms-a.md) | Pending | ~½ day |
| 6 | [Config forms B — campaigns + workflow editors](step-6-config-forms-b.md) | Pending | ~1 day |
| 7 | [Settings forms](step-7-settings-forms.md) | Pending | ~½ day |
| 8 | [Contacts CSV import — validation + errors.csv](step-8-contacts-csv-import.md) | Pending | ~½ day |
| 9 | [Leads CSV import — new validation rules](step-9-leads-csv-import.md) | Pending | ~½ day |
| 10 | [Catalog CSV import — validation + errors.csv](step-10-catalog-csv-import.md) | Pending | ~½ day |

**Total: ~5 working days.** Each step is independently verifiable; pause and report after each per rule 9.

## Dependencies

- No blockers. This track binds against existing form components and existing import services — nothing new is required upstream.
- Steps 8, 9, 10 depend on Step 1 (shared backend validators).
- Steps 2–7 depend on Step 1 (shared frontend validators).
- Otherwise steps are independent — the order below is by domain, not by dependency.

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Step 1 (foundation) | 3 modified + 2 new + 2 test files | Extends `commonValidators` + adds `shared/validators.py` and `shared/import_errors.py` on the backend. |
| Steps 2–7 (forms) | ~40 modified across ~15 modules | In-place edits — no new component files. Most are one-line changes swapping `Validators.email` → `commonValidators.email` or adding a `commonValidators.phone` to a control that had none. |
| Steps 8–10 (imports) | ~9 modified + 2 new endpoints | Wire validators into existing `service.py` / `tasks.py`; add `errors.csv` route + response for contacts and catalog. |

**Total ~55 files across 10 steps.** Every step within the < 10 files / < 400 lines rule.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Frontend and backend validate every field using the **same regex**. | Regex constants live in `api/src/app/shared/validators.py` and are mirrored verbatim in `app/src/app/shared/validators/custom-validators.ts`. A backend unit test asserts the two are in sync (compares serialized patterns). |
| Every CSV import validates row-level before write. | Each import service calls `shared.validators.<rule>()` inside its row loop; failed rows raise into a collected `errors` list, never persisted. |
| Every failed row produces a downloadable, row-numbered error record. | `shared.import_errors.write_errors_csv()` is the only writer for import error output. All three imports call it. |
| Auth-pages validators are importable from anywhere. | The base validators live in `app/src/app/shared/validators/` (not `features/user/core/shared/`) so the accounts pages can import them without crossing the user-feature boundary. |
| No form component defines its own regex. | Code review + `simplify` skill flag any `Validators.pattern(/.../)` in a component file — everything routes through `commonValidators`. |

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. All scope is in `core/` and `shared/`.
- ✅ Rule 2: No new tables. No `org_id` question — nothing DB-side.
- ✅ Rule 3: Custom fields layered model unaffected. Step 1 wires the same validators into the dynamic-form builder so custom email / phone / text fields validate identically.
- ✅ Rule 4: Dynamic-form rendering unchanged — this track *reinforces* it (custom-field validators come from the same pool).
- ✅ Rule 5: Sidebar registry unchanged.
- ✅ Rule 6: Permission registry unchanged.
- ✅ Rule 7: `pack.yaml` untouched. Validators are vertical-neutral.
- ✅ Rule 8: Each step verifiable in < 30 min. File count and line budget respect the < 10 / < 400 ceiling.
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs, no shortcuts. Every validator is production-ready with unit test coverage.

## After this track

- The CRM stops accepting garbage input at every entry point — direct form, API call, CSV upload.
- Support burden drops (no more "why is my contact name three emojis").
- CSV imports report *why* every skipped row was skipped, with row numbers, so operators can fix and re-upload.
- The single-source-of-truth regex means when a rule needs to loosen or tighten later (e.g. accepting names with `/`), we change one file.
