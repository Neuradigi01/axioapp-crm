# Step 16 — Welcome message + out-of-hours auto-reply

**Goal:** Wire the greeting / away message text stored in Step 11 to actually fire on inbound webhooks. New-contact greeting on first message; out-of-hours auto-reply based on Step 11's business hours.
**Status:** COMPLETED
**Depends on:** Step 11 (storage for greeting + away + business hours), Step 8 (templates exist for out-of-session greetings).

---

## Scope

In-scope:
- Service `auto_reply.py`:
  - On inbound webhook → detect first-time contact (no prior conversation row) → send greeting message.
  - On inbound webhook → check business hours → if out-of-hours → send away message.
  - Template-variable substitution: `{{contact.first_name}}`, `{{org.name}}`, etc.
  - Idempotency: only one auto-reply per contact per 24h per type.
  - In-session vs out-of-session: in-session uses free text; out-of-session requires an approved template (referenced by id in settings).
- Endpoints:
  - `GET /api/v1/whatsapp/auto-reply/settings` — current greeting + away + enabled flags + linked templates
  - `PATCH /api/v1/whatsapp/auto-reply/settings`
- Settings extension: `greeting_enabled BOOL`, `away_enabled BOOL`, `greeting_template_id UUID NULL` (for out-of-session), `away_template_id UUID NULL`.
- Frontend: small section on Business Profile page (Step 11) — toggles + text editors with live preview + variable inserter + linked-template picker (for out-of-session fallback).

Out of scope:
- Keyword triggers — Step 17.
- Auto-assignment — Step 18.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/auto_reply.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | Add enabled flags + template FKs |
| `API/alembic/versions/<ts>_auto_reply_settings.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Dispatch to auto_reply pipeline on inbound |
| `API/src/app/core/integrations/whatsapp/router.py` | Settings endpoints |
| `APP/.../whatsapp/business-profile/auto-reply-section.component.ts` | **NEW** (extends Step 11's page) |
| `API/tests/integrations/test_auto_reply.py` | **NEW** |

**~7 files. ~400 lines.**

## Plan

1. Migration adds enabled flags + template FKs (nullable).
2. Service: pipeline order — first-time greeting → out-of-hours away → keyword (Step 17). Each step short-circuits if it sent something.
3. Variable substitution helper shared with Step 11's editor preview.
4. In-session check uses Step 15's session helper.
5. Frontend: toggles + textareas + template picker for out-of-session fallback.
6. Tests: first-time greeting fires once; second message same contact within 24h does not re-greet; out-of-hours fires; template-only path when out-of-session.

## DB changes / migrations

Add 4 columns to `tbl_whatsapp_account_configs`.

## Tests

8 pytest cases.

## Smoke

```
1. Enable greeting "Hello {{contact.first_name}}, welcome to {{org.name}}!"
2. New contact "Asha" sends "Hi" → receives "Hello Asha, welcome to Neuradigi!" within seconds.
3. Asha sends another message → no re-greeting (24h cooldown).
4. Set hours Mon-Sat 10-19. At 11pm enable away "We're closed; back at 10am."
5. Inbound from new contact at 11pm → greeting + away both sent.
6. Out-of-session window: enable greeting_template "welcome_v1" → new contact greeted via template.
7. Disable both → no auto-replies.
```

## Risks

- Reply loops with other bots — cooldown + skip if contact's prior message was itself an automation.
- Out-of-session greeting requires an approved template — refuse to save if template not approved.

## Self-check (10 rules)

All `core/integrations/whatsapp/`. ✓. org_id + RLS. ✓. No custom-field changes. ✓. Static settings form. ✓ N/A. No registry change. ✓. Existing `whatsapp.business_profile.manage` permission. ✓. pack.yaml untouched. ✓. 7 files / ~400 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 16 — Welcome + out-of-hours auto-reply
Files: 7
Verify: first-message greeting + business-hours away + variable substitution + template fallback.
Tests: 8 pytest cases.
Next: Step 17 — keyword triggers.
Awaiting "proceed".
```
