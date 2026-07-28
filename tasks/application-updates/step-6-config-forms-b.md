# Step 6 — Config forms B (campaigns + workflow editors)

**Goal:** Apply shared validators to the campaign-creation wizard and to the workflow-canvas node editors (send-email, send-sms, send-whatsapp, wait, trigger, branch, and the rest) so multi-step configuration surfaces enforce the same input rules as the standalone forms in Steps 2–5.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** Pending
**Depends on:** Step 1 (shared validators), Step 5 (template validators — several workflow editors reuse the template rules).

---

## Scope

Two clusters — one large wizard and a family of 15+ small canvas editors. The wizard gets a full pass; the canvas editors get an audit pass with a documented per-editor validator table. No new components, no logic changes.

**Cluster A — Campaigns wizard:**

- `app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts`

**Cluster B — Workflow canvas editors** (list is the current file inventory; adjust if some are missing):

- `app/src/app/features/user/core/workflows/canvas/editors/send-email-editor.component.ts`
- `.../send-sms-editor.component.ts`
- `.../send-whatsapp-editor.component.ts`
- `.../send-push-editor.component.ts`
- `.../wait-editor.component.ts`
- `.../trigger-editor.component.ts`
- `.../branch-editor.component.ts`
- `.../update-record-editor.component.ts`
- `.../assign-user-editor.component.ts`
- `.../create-task-editor.component.ts`
- `.../webhook-editor.component.ts`
- `.../ai-action-editor.component.ts`
- (plus any others under `.../canvas/editors/`)

## Per-form changes

### Campaigns wizard

The wizard is stepped; validators attach at the step-form level, not the wizard root:

| Step | Field | New validator |
|---|---|---|
| 1 – Basics | `name` | `Validators.required`, `commonValidators.maxLength(255)`, `commonValidators.trimmedRequired` |
| 1 – Basics | `description` | `commonValidators.maxLength(2000)` |
| 2 – Audience | `segment_id` | picklist validator |
| 2 – Audience | `manual_recipient_count` (if any) | `Validators.min(1)`, `Validators.max(1_000_000)` |
| 3 – Channel | `channel` | picklist validator (`email` / `whatsapp`) — enforces the Campaigns v1 scope locked in the "Campaigns scope" project memory |
| 4 – Template | `template_id` | required + async check that the template exists (already server-side; add client presence check) |
| 5 – Schedule | `send_at` | `dateNotPast` when `send_mode === 'scheduled'` |
| 5 – Schedule | A/B split percent | `Validators.min(1)`, `Validators.max(99)` |
| 5 – Schedule | throttle rate | `Validators.min(1)`, `Validators.max(10_000)` per hour |

The wizard's "Next" button reflects the current step's `formGroup.valid`. The submit button on the final step requires all step groups valid.

### Workflow canvas editors

Each editor is small (typically 2–6 fields). Table of key validators per editor:

| Editor | Field | Validator |
|---|---|---|
| **send-email** | `template_id` | picklist required |
| **send-email** | `to_field` | picklist (`contact.email` / `lead.email` / `custom.<key>`) |
| **send-email** | `override_subject` (if present) | `commonValidators.maxLength(998)` |
| **send-sms** | `template_id` | picklist required |
| **send-sms** | `to_field` | picklist |
| **send-whatsapp** | `template_id` | picklist required |
| **send-whatsapp** | template variable values | `waVariablesValidator` (from Step 5) — must satisfy the template's variable count |
| **send-push** | `template_id` | picklist required |
| **wait** | `duration_value` | `Validators.required`, `Validators.min(1)`, `Validators.max(365)` |
| **wait** | `duration_unit` | picklist (`minutes` / `hours` / `days`) |
| **wait** | `until_datetime` (absolute mode) | `dateNotPast` |
| **trigger** | `event_key` | picklist required (from server-provided registry) |
| **trigger** | `entity_type` | picklist |
| **branch** | `field` | picklist |
| **branch** | `operator` | picklist |
| **branch** | `value` | required; type-checked against `field` (numeric field → numeric value, date field → ISO date, etc.) — new `typedValueValidator(field)` factory added to shared validators |
| **update-record** | `field` | picklist |
| **update-record** | `new_value` | `typedValueValidator(field)` |
| **assign-user** | `assignment_mode` | picklist (`round_robin` / `specific_user` / `least_loaded`) |
| **assign-user** | `user_id` | required when mode = `specific_user` (via `withRequiredIf`) |
| **create-task** | `title` | `Validators.required`, `commonValidators.trimmedRequired`, `commonValidators.maxLength(255)` |
| **create-task** | `due_offset_days` | `Validators.min(0)`, `Validators.max(365)` |
| **webhook** | `url` | `Validators.required`, `commonValidators.url` |
| **webhook** | `method` | picklist (`GET` / `POST` / `PUT` / `DELETE`) |
| **webhook** | `timeout_seconds` | `Validators.min(1)`, `Validators.max(60)` |
| **ai-action** | `prompt` | `Validators.required`, `commonValidators.maxLength(4000)` |
| **ai-action** | `output_field` | picklist |

## Shared additions

- `typedValueValidator(fieldDef)` — factory that checks the input string parses to the declared type (number / date / boolean / string). Added to `app/src/app/shared/validators/custom-validators.ts`.

## Files to touch

Bounded to keep the step under budget:

| File | Action |
|---|---|
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.ts` | modified — per-step form-group validators |
| `app/src/app/features/user/core/campaigns/create-campaign-modal.component.html` | modified — error messages on each step |
| `app/src/app/features/user/core/workflows/canvas/editors/*.component.ts` | modified — one small edit per editor (up to ~7 editor files) |
| `app/src/app/features/user/core/workflows/canvas/editors/*.component.html` | modified — error messages (mirroring the .ts edits) |
| `app/src/app/shared/validators/custom-validators.ts` | modified — `typedValueValidator` |

**If the editor family exceeds 8 files in this pass, split into 6a (Campaigns + send-* editors) and 6b (remaining editors) — flag before starting the step.** Target ~10 files for this step; the rest carry into a small follow-up.

## Tests

- Campaigns wizard: step-1 name blank → Next disabled; step-5 `send_at` past → error; A/B percent 0 rejected.
- send-whatsapp editor: template with 3 variables + only 2 values supplied → error.
- wait editor: 0 days rejected; -1 days rejected.
- branch editor: numeric field with value `"abc"` → error.
- webhook editor: URL `"example.com"` (no scheme) → error.

## Smoke

```
# Manual walk against Ajay's Workspace:
# 1. /user/campaigns → New campaign → try Next with blank name → button disabled.
# 2. Complete wizard with A/B split = 0 → error at step 5.
# 3. /user/workflows → open any workflow → drop a "Wait" node → duration 0 → error.
# 4. Add a "Webhook" node → URL "example.com" → error.
# 5. Add a "Send WhatsApp" node → template with 2 vars, fill only 1 → error.
```

## Risks

- **Editor inventory drift** — the canvas has 15+ editors and grows as workflow features expand. Any editor added after this step needs the same validator pattern. Add a code-review note (or a `simplify` check) that new editor .ts files must import from `commonValidators`.
- **`typedValueValidator` complexity** — depends on the runtime `FieldDef` shape. If the shape isn't uniform across trigger / branch / update-record, the factory may need per-editor variants. Confirm during step kickoff.
- **Wizard step-navigation regressions** — the wizard's "Next" button already reads from `formGroup.valid`. Adding validators means the button may disable in states where it was previously enabled. Any regressions get called out in smoke.

## Rollback

Revert the touched files. Wizard and canvas keep working with looser client-side validation; server-side rejects still fire.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. Workflows and campaigns are in `core/`.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Custom-field values inside branch / update-record editors go through the same shared validators.
- ✅ Rule 4: Dynamic rendering unchanged.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched. Editor list is vertical-neutral.
- ✅ Rule 8: Split plan (6a / 6b) if the editor count blows the budget.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs.
