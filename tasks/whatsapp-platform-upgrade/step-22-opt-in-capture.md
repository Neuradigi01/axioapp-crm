# Step 22 — Opt-in capture (storage + UI + audit + send guard)

**Goal:** DPDP / GDPR-ready opt-in surface. Contacts have explicit opt-in status; transitions recorded in immutable consent log; bulk import / form widget / inbound flows update status correctly; campaign send refuses opted-out contacts.
**Status:** Pending
**Depends on:** Phase 1 closed (any time after).

---

## Scope

In-scope:
- Extend `tbl_contacts` (org-scoped, RLS):
  - `whatsapp_opt_in_status` ENUM (`implicit` / `opted_in` / `opted_out` / `never_contacted`)
  - `whatsapp_opt_in_source` ENUM (`form_widget` / `bulk_import` / `manual_entry` / `inbound_first_message` / `explicit_opt_in_link`)
  - `whatsapp_opt_in_recorded_at`, `whatsapp_opt_in_recorded_by_user_id`
  - `whatsapp_opt_out_recorded_at`, `whatsapp_opt_out_reason TEXT`
- New table `tbl_consent_events` (org-scoped, RLS, immutable via append-only — no UPDATE/DELETE grants):
  - org_id, contact_id, channel, old_status, new_status, source, actor_user_id (null=system), recorded_at, ip_address NULL, request_evidence JSONB
- Auto-rules:
  - Inbound from `never_contacted` → auto `implicit` + audit event.
  - Inbound matches STOP / OPT OUT / REMOVE / अनसब्सक्राइब / बंद करो → auto `opted_out` + send confirmation template + log event.
- Bulk import wizard: required "opt-in source" step.
- Form widget: required consent checkbox.
- Campaign send guard: refuses marketing templates to `opted_out`; warns + requires confirmation for `implicit`.
- Endpoints:
  - `GET /api/v1/contacts/{id}/opt-in` — current + history
  - `POST /api/v1/contacts/{id}/opt-in` — manual record
  - `POST /api/v1/contacts/{id}/opt-out`
- New permission `whatsapp.opt_in.manage` for manual overrides.
- Contacts list: opt-in chip column.
- Contact detail panel: opt-in section with history timeline.

Out of scope:
- DPDP right-to-access export — Step 23 (consolidated with DND + export).
- DPDP erasure (full data deletion) — defer to separate compliance track.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/contacts/models.py` | Opt-in columns |
| `API/alembic/versions/<ts>_opt_in_and_consent_events.py` | **NEW** + immutability trigger |
| `API/src/app/core/contacts/router.py` | Opt-in endpoints |
| `API/src/app/core/contacts/consent_service.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/webhook.py` | STOP detection + inbound first-message flip |
| `API/src/app/core/campaigns/send_guard.py` | **NEW** opt-in check |
| `APP/.../contacts/list/opt-in-chip.component.ts` | **NEW** |
| `APP/.../contacts/detail/opt-in-section.component.ts` | **NEW** |
| `APP/.../bulk-import/opt-in-step.component.ts` | **NEW** |
| `APP/.../embedded-widget/consent-checkbox.component.ts` | **NEW** |
| `APP/.../campaigns/create/opt-in-warning.component.ts` | **NEW** |
| `API/tests/contacts/test_opt_in.py` | **NEW** |

**~12 files. ~800 lines.**

## Plan

1. Migration: opt-in cols + consent events table; DB-level GRANT only INSERT on consent_events; trigger blocks UPDATE/DELETE.
2. Service: transition function with audit-event emit; idempotent on identical transitions.
3. STOP keyword regex: English + Hindi initially; extensible.
4. Confirmation template requirement on opt-out — refuse webhook flip if no opt-out template configured.
5. Bulk import: opt-in step mandatory; existing flow gets a new required field.
6. Form widget: consent checkbox above submit; persists to contact opt-in on lead-create.
7. Campaign guard: pre-send filter + warning UX.
8. Tests cover all transitions + STOP detection + permission + send-guard.

## DB changes / migrations

Many columns + new table + immutability trigger.

## Tests

12 pytest + 4 Jest.

## Smoke

```
1. Bulk import wizard: cannot proceed without selecting opt-in source.
2. Form widget: consent checkbox visible by default; submit creates contact with opted_in.
3. Existing contact (implicit) sends inbound "Hi" → flip to implicit + event logged.
4. Existing contact sends "STOP" → flip to opted_out + confirmation template sent + event logged.
5. Campaign create modal: select opted-out segment → blocked. Implicit segment → warning + confirm.
6. Manual opt-in via contact detail → event logged.
7. Sales-Junior cannot manually override → 403.
8. Consent events table: DB rejects UPDATE/DELETE.
```

## Risks

- Backfill existing contacts as `implicit` + show one-time banner to owners.
- STOP localization expansion — keep regex extensible.
- Opted-out re-opt-in flow (START keyword): require manual action, not auto re-flip.

## Self-check (10 rules)

`core/contacts/` + `core/integrations/whatsapp/` + `core/campaigns/`. ✓. org_id + RLS + immutability trigger. ✓. Opt-in fields first-class (intentional override of Rule 3). ✓ documented. New permission registered. ✓. pack.yaml untouched. ✓. 12 files / ~800 lines (at edge — split if needed). ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 22 — Opt-in capture
Files: 12
Verify: opt-in flow end-to-end; STOP auto-flip; campaign guard; immutability of consent_events.
Tests: 12 pytest + 4 Jest.
Next: Step 23 — DND / block list + DPDP export.
Awaiting "proceed".
```
