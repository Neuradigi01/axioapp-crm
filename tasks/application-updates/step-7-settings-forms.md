# Step 7 — Settings forms

**Goal:** Apply shared validators to the settings-page forms — user profile, team-tab inline edits, SMTP sender identity, sender-code verify, add-domain, compliance settings, standard-field-edit modal — so every admin configuration surface enforces the same input rules as the rest of the CRM.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** COMPLETED — profile, team, standard-field-edit, SMTP sender, and add-domain forms wired to shared validators. Two new hostname helpers added (`hostnameValidator` for RFC-1123 and `hostnameApexValidator` for apex-only DKIM domains). Profile drops manual password-match check for `matchFieldValidator`. Team-tab layers a picklist validator on role_id once roles load (dynamic). Add-domain modal swaps its local regex for `hostnameApexValidator`. SMTP password max kept at 4096 (existing) — see Notes. tsc + eslint + prettier all clean. Step 6 (campaigns wizard + workflow editors) skipped by user; standard-field modal's `default_value` typedValueValidator deferred with it.
**Depends on:** Step 1 (shared validators).

---

## Scope

Settings-page tabs and dialogs — no new components, no logic changes. All under `app/src/app/features/user/core/settings/`.

Files:

1. `settings/tabs/profile-tab.component.ts`
2. `settings/tabs/team-tab.component.ts`
3. `settings/tabs/standard-field-edit-modal.component.ts`
4. `settings/integrations/add-sender-identity-modal.component.ts` (SMTP)
5. `settings/integrations/verify-sender-code-modal.component.ts`
6. `settings/sender-setup/add-domain-modal.component.ts`
7. `settings/general/compliance-settings.component.ts`

## Per-form changes

### Profile tab

| Field | Before | After |
|---|---|---|
| `full_name` | `Validators.required`, `Validators.maxLength(255)` | add `commonValidators.name` |
| `phone` | (none) | `commonValidators.phone` |
| `current_password` | `Validators.required` | `Validators.required`, `Validators.maxLength(128)` |
| `new_password` | `Validators.required`, `Validators.minLength(8)`, `Validators.maxLength(255)` | replace with `Validators.required`, `commonValidators.password` |
| `confirm_password` | `Validators.required` (no match validator; check in code) | `Validators.required`, `Validators.maxLength(128)`, `matchFieldValidator('new_password')` |

Remove the manual `confirm_password === new_password` check from the submit handler.

### Team tab (inline user edit)

Per-row inline `FormGroup`:

| Field | Before | After |
|---|---|---|
| `full_name` | (none) | `Validators.required`, `commonValidators.name` |
| `phone` | (none) | `commonValidators.phone` |
| `role_id` | (none) | picklist validator |
| `is_active` | boolean | unchanged |

### Standard field edit modal

Managers override standard-field visibility / required. The form's own inputs:

| Field | Before | After |
|---|---|---|
| `label_override` | `Validators.maxLength(128)` | add `commonValidators.trimmedRequired` when non-empty |
| `help_text_override` | (none) | `commonValidators.maxLength(500)` |
| `default_value` | (none) | `typedValueValidator(fieldDef)` (from Step 6) |

### Add sender identity modal (SMTP)

| Field | Before | After |
|---|---|---|
| `from_address` | required (assumed) | `Validators.required`, `commonValidators.email`, `commonValidators.maxLength(254)` |
| `display_name` | required (assumed) | `Validators.required`, `commonValidators.name` |
| `smtp_host` | required (assumed) | new `hostnameValidator` — pattern `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$` — added to shared validators |
| `smtp_port` | required (assumed) | `Validators.required`, `Validators.min(1)`, `Validators.max(65535)` |
| `smtp_username` | required (assumed) | `Validators.required`, `Validators.maxLength(254)` |
| `smtp_password` | required (assumed) | `Validators.required`, `Validators.maxLength(256)` |
| `tls_mode` | required (assumed) | picklist validator (`STARTTLS` / `SSL_TLS` / `NONE`) |

### Verify sender code modal

| Field | Before | After |
|---|---|---|
| `code` | `Validators.required`, `Validators.pattern(/^\d{6}$/)` | unchanged (already strict; leave as-is) |

### Add domain modal

| Field | Before | After |
|---|---|---|
| `domain` | (none) | `Validators.required`, `hostnameValidator` — apex domain only (`example.com`, not `mail.example.com`) — add a `hostnameApexValidator` variant that rejects hosts with more than the effective TLD + 1 label |

### Compliance settings

| Field | Before | After |
|---|---|---|
| `unsubscribe_footer_html` | (none) | `commonValidators.maxLength(2000)` |
| `dpo_email` | (none) | `commonValidators.email` |
| `retention_days` | (none) | `Validators.min(30)`, `Validators.max(3650)` |

## Shared additions

- `hostnameValidator` — RFC-1123 hostname regex.
- `hostnameApexValidator` — same but rejects subdomains beyond apex.

Both added to `app/src/app/shared/validators/custom-validators.ts`.

## Files to touch

| File | Action |
|---|---|
| `settings/tabs/profile-tab.component.ts` | modified |
| `settings/tabs/profile-tab.component.html` | modified — error messages |
| `settings/tabs/team-tab.component.ts` | modified |
| `settings/tabs/standard-field-edit-modal.component.ts` | modified |
| `settings/integrations/add-sender-identity-modal.component.ts` | modified |
| `settings/integrations/add-sender-identity-modal.component.html` | modified — error messages |
| `settings/sender-setup/add-domain-modal.component.ts` | modified |
| `settings/general/compliance-settings.component.ts` | modified |
| `app/src/app/shared/validators/custom-validators.ts` | modified — 2 additional validators |

**~9 files.** Within the per-step rule.

## Tests

- Profile tab: password mismatch rejected via validator (not code); weak new password rejected.
- Team tab inline: row with name digits rejected.
- SMTP sender: port 0 rejected; port 70000 rejected; malformed host `"smtp..example.com"` rejected.
- Add domain: subdomain `"mail.example.com"` rejected (apex-only rule).
- Compliance: retention 10 rejected (min 30); retention 4000 rejected (max 3650).

## Smoke

```
# Manual walk against Ajay's Workspace:
# 1. /user/settings/profile → Change password → mismatch rejected inline.
# 2. /user/settings/team → click a user row → clear name → error.
# 3. /user/settings/integrations → Add sender → port 999999 → error.
# 4. /user/settings/senders → Add domain → "mail.example.com" → error.
# 5. /user/settings/compliance → retention 10 → error.
```

## Risks

- **Team-tab inline edits** — inline forms in a table are trickier to error-render. Confirm during kickoff whether errors show as row-level tooltips or under-cell — match whatever pattern the table already uses; do not add a new error UI.
- **Add-domain apex-only rule** — some organizations legitimately want subdomain-scoped DKIM. If that surfaces, the validator becomes optional (`hostnameApexValidator` for standard flow, `hostnameValidator` for advanced flow behind a toggle). Do not add the toggle in this step — call out and defer.
- **SMTP password max 256** — some enterprise SMTP servers accept longer secrets. If a real user hits it, raise the ceiling; 256 is a safe starting point.

## Rollback

Revert the 9 files.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Standard-field-edit modal touches custom-field-adjacent config; its `default_value` uses `typedValueValidator`, consistent with Step 6.
- ✅ Rule 4: Dynamic rendering unchanged.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 9 files, small changes each.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs.
