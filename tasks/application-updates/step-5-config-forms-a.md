# Step 5 — Config forms A (custom fields + templates)

**Goal:** Apply shared validators to the custom-field definition form and to all five template editors (email, SMS, WhatsApp, push, Facebook/Instagram) so template + custom-field configuration is bounded and format-checked before it hits the API.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** Pending
**Depends on:** Step 1 (shared validators).

---

## Scope

Six component files under two modules:

1. `app/src/app/features/user/core/custom-fields/field-form.component.ts`
2. `app/src/app/features/user/core/templates/editor/email-form.component.ts`
3. `app/src/app/features/user/core/templates/editor/sms-form.component.ts`
4. `app/src/app/features/user/core/templates/editor/wa-form.component.ts`
5. `app/src/app/features/user/core/templates/editor/push-form.component.ts`
6. `app/src/app/features/user/core/templates/editor/fb-form.component.ts`

## Per-form changes

### Custom field form

| Field | Before | After |
|---|---|---|
| `field_key` | `Validators.required`, custom `fieldKeyValidator` (`^[a-z][a-z0-9_]{1,49}$`) | unchanged (already strict) |
| `field_label` | `Validators.required`, `Validators.maxLength(128)` | add `commonValidators.trimmedRequired` |
| `field_type` | `Validators.required` | picklist validator (must be in the fixed enum) |
| `choices_csv` (for select / multiselect) | (none) | new `choicesCsvValidator` — splits on comma, rejects duplicates, rejects entries > 64 chars, caps at 100 choices; added to shared frontend validators |

### Email template form

| Field | Before | After |
|---|---|---|
| `subject` | `Validators.required`, `Validators.maxLength(998)` | add `commonValidators.trimmedRequired` |
| `preview_text` | `Validators.maxLength(190)` | unchanged |
| `body_text` | `Validators.maxLength(65535)` | unchanged |
| `body_html` | `Validators.maxLength(200000)` | tighten to `100000` (200 KB is excessive for a template; matches common ESP limits) |
| Cross-field: at least one of `body_text` / `body_html` | enforced in service | add a group-level validator so the submit button reflects the state client-side |

### SMS template form

| Field | Before | After |
|---|---|---|
| `body_text` | (no maxLength validator; only a UI counter) | `Validators.required`, `Validators.maxLength(1600)` (10 concatenated GSM-7 segments) |
| `dlt_entity_id` | (none) | pattern `^[0-9]{15,25}$` when present |
| `dlt_template_id` | (none) | pattern `^[0-9]{15,25}$` when present |
| `dlt_content_category` | (none) | picklist validator |
| `dlt_header` | (none) | pattern `^[A-Z0-9]{2,11}$` (TRAI sender-ID rules — 2–11 alphanumeric) |
| `dlt_principal_entity_id` | (none) | `Validators.maxLength(64)` |

### WhatsApp template form

| Field | Before | After |
|---|---|---|
| `name` | `Validators.required` (assumed) | `Validators.required`, pattern `^[a-z0-9_]{1,512}$` (Meta template-name rule) |
| `body_text` | `Validators.required`, `Validators.maxLength(1024)` | unchanged if already present |
| `header_text` | `Validators.maxLength(60)` | ensure |
| `footer_text` | `Validators.maxLength(60)` | ensure |
| variable-count check | enforced server-side | mirror client-side — variable placeholders like `{{1}}`, `{{2}}` must be sequential, no gaps, max 10; new `waVariablesValidator` |

### Push template form

| Field | Before | After |
|---|---|---|
| `title` | required | `Validators.required`, `Validators.maxLength(65)` (iOS notification limit) |
| `body` | required | `Validators.required`, `Validators.maxLength(240)` (iOS + Android common ceiling) |
| `icon_url` | (none) | `commonValidators.url` |

### Facebook / Instagram template form

| Field | Before | After |
|---|---|---|
| `message` | required | `Validators.required`, `Validators.maxLength(2000)` (Messenger limit) |
| `image_url` | (none) | `commonValidators.url` |
| `cta_url` | (none) | `commonValidators.url` |

## Shared additions under Step 1's foundation

New validators consumed here, added to `app/src/app/shared/validators/custom-validators.ts`:

- `choicesCsvValidator(control)` — CSV parser, dedup, per-entry length cap, total count cap.
- `waVariablesValidator(control)` — parses `{{n}}` placeholders, checks sequentiality.
- `picklistValidator(allowed: string[])` — factory; asserts value ∈ list.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/custom-fields/field-form.component.ts` | modified |
| `app/src/app/features/user/core/templates/editor/email-form.component.ts` | modified |
| `app/src/app/features/user/core/templates/editor/sms-form.component.ts` | modified |
| `app/src/app/features/user/core/templates/editor/wa-form.component.ts` | modified |
| `app/src/app/features/user/core/templates/editor/push-form.component.ts` | modified |
| `app/src/app/features/user/core/templates/editor/fb-form.component.ts` | modified |
| `app/src/app/features/user/core/templates/editor/*.html` | modified — error messages (6 templates) |
| `app/src/app/shared/validators/custom-validators.ts` | modified — 3 additional validators |

**~10 files (counting HTML templates).** Right at the ceiling. If SMS or WA form validators grow, split WA into its own step.

## Tests

- Field form: duplicate `choices_csv` entries rejected; `field_key` regex regression preserved.
- Email template: > 100 KB HTML body rejected; missing both text and HTML → group-level error.
- SMS template: DLT header `"abc"` (lowercase) rejected; header 12 chars rejected; entity_id with letters rejected.
- WhatsApp template: variables `{{1}}, {{3}}` (gap) rejected; name with uppercase rejected.
- Push template: body > 240 chars rejected; malformed icon URL rejected.
- FB template: bad `image_url` rejected.

## Smoke

```
# Manual browser walk:
# 1. /user/settings/custom-fields → New field → duplicate choices "Hot, hot, HOT" → error.
# 2. /user/templates → New email → submit with only subject (no body) → group error.
# 3. New SMS → header "cool_sender" → error; entity_id "abc123" → error.
# 4. New WhatsApp template → body with {{1}} and {{3}} but no {{2}} → error.
# 5. New push notification → body of 300 chars → error.
```

## Risks

- **Meta / TRAI regex authority** — the DLT and Meta template-name regexes are documented but their vendors quietly update rules. If a submission that passes our regex is later rejected by Meta / the DLT provider, that's a downstream failure we surface via the existing template-approval status card (per the "Campaigns scope" project memory: template approval status must render in the CRM UI). We do not attempt to be *stricter* than Meta.
- **Existing templates that don't meet new rules** — the modal will flag them on next edit; user must fix before re-saving. Existing send behavior is not blocked.

## Rollback

Revert the ~10 files.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Custom fields — this step *is* the custom-field-definition form; its own validation gets tightened. Dynamic rendering of custom-field values (contact / lead modals) already flows through Step 1's validator chain.
- ✅ Rule 4: Dynamic rendering unchanged.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: ≤ 10 files, split-if-grows plan in place for WhatsApp.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs.
