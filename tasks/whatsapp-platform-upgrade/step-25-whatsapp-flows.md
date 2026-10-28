# Step 25 — WhatsApp Flows (in-chat forms)

**Goal:** Ship Meta's WhatsApp Flows feature — in-chat forms (appointment booking, lead capture, feedback) that customers fill inside WhatsApp without leaving the conversation. Submissions land back in Core CRM as new leads / appointments / feedback rows.
**Status:** COMPLETED
**Depends on:** Phase 1 (manageable token), Step 8 (template management patterns).

---

## Scope

In-scope:
- Table `tbl_whatsapp_flows` (org-scoped, RLS): id, org_id, name, json_definition JSONB (Meta Flow spec), category ENUM (`appointment_booking` / `lead_capture` / `feedback` / `signup` / `custom`), status (draft/published/archived), meta_flow_id, created_by_user_id, created_at.
- Service `flows_service.py` wrapping Meta Graph:
  - `POST /{waba_id}/flows` (create)
  - `POST /{flow_id}/assets` (upload JSON)
  - `POST /{flow_id}/publish`
  - `DELETE /{flow_id}` (deprecate)
- Endpoints:
  - `GET /api/v1/whatsapp/flows`
  - `POST /api/v1/whatsapp/flows`
  - `PATCH /api/v1/whatsapp/flows/{id}`
  - `POST /api/v1/whatsapp/flows/{id}/publish`
  - `POST /api/v1/whatsapp/flows/{id}/test-send`
- Inbound webhook: handle `nfm_reply` event → persist to new `tbl_whatsapp_flow_submissions` (org-scoped) linking contact + flow + submitted data.
- Auto-actions on submission based on category:
  - `appointment_booking` → create appointment row in existing appointments module
  - `lead_capture` → create lead row
  - `feedback` → persist to feedback table (create if needed)
  - `custom` → emit webhook
- Permission `whatsapp.flows.manage`.
- Frontend `/user/whatsapp/flows`:
  - List view with category badges + status.
  - Create: pick template (Appointment / Lead capture / Feedback / Sign-up / Blank custom) → simple builder.
  - Builder (lightweight): drag screens with inputs (text, number, dropdown, date, multi-select), branching, terminal action.
  - Test send: enter phone → receive flow in WhatsApp.

Out of scope:
- Full visual flow designer with arbitrary JSON editing — templates only in v1.
- Furniture-specific flows (custom-order quote) — belongs in `packs/furniture/`.

## Pre-step decision (escalate to user)

- **Which 2-3 flow templates ship first?** Recommend: Appointment booking, Lead capture, Feedback. Confirm.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/flows_service.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | flows + submissions tables |
| `API/alembic/versions/<ts>_whatsapp_flows.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/flows_router.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Parse `nfm_reply` |
| `API/src/app/core/integrations/whatsapp/module.py` | Register permission |
| `API/src/app/core/integrations/whatsapp/flow_templates/` | **NEW** JSON template files (appointment, lead, feedback) |
| `APP/.../whatsapp/flows/flows-page.component.ts` | **NEW** |
| `APP/.../whatsapp/flows/flow-template-picker.component.ts` | **NEW** |
| `APP/.../whatsapp/flows/flow-builder.component.ts` | **NEW** lightweight builder |
| `APP/.../whatsapp/flows/flow-preview.component.ts` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | Add lazy route |
| `API/tests/integrations/test_whatsapp_flows.py` | **NEW** |

**~13 files. ~1100 lines.**

## Plan

1. Migration: flows + submissions tables; FK to contact + (optional) lead/appointment row.
2. Meta service wraps create / upload / publish / delete.
3. Bundled JSON templates checked into repo for the 3 starter categories.
4. Builder: signal-driven; renders strongly-typed input fields per template.
5. nfm_reply handler: parse submission, map to category-specific action, persist + audit.
6. Tests cover: each starter template publish + submission round-trip + auto-action dispatch.

## DB changes / migrations

Two new tables.

## Tests

10 pytest + 3 Jest.

## Smoke

```
1. /user/whatsapp/flows → list empty.
2. Create flow from Appointment template → builder shows date + time + service inputs.
3. Publish → flow appears at Meta.
4. Test send to own phone → flow opens in WhatsApp.
5. Fill flow + submit → submission persists → appointment row created in CRM.
6. Repeat for Lead capture template → lead row created.
7. Repeat for Feedback template → feedback row created.
8. Edit + republish a flow → Meta version updates.
9. Sales-Junior without flows.manage → can view list, cannot create.
```

## Risks

- Meta Flows spec evolves quickly — pin api_version + plan for annual review.
- Test-send requires registered phone for the WABA — document.
- Lightweight builder ≠ full designer; document limits clearly.

## Self-check (10 rules)

All `core/integrations/whatsapp/`. ✓. org_id + RLS. ✓. Flow JSON is Meta-spec'd (not custom-field engine). ✓. Static templates. ✓ N/A. New sub-page registered. ✓. New permission. ✓. pack.yaml untouched. ✓. 13 files / ~1100 lines (over budget — split builder UI from backend at execution time). ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 25 — WhatsApp Flows
Files: 13 (consider split into 25a backend + 25b UI if over budget at execution)
Verify: 3 starter templates publishable + submissions create CRM rows.
Tests: 10 pytest + 3 Jest.
Next: Step 26 — QR + wa.me links.
Awaiting "proceed".
```
