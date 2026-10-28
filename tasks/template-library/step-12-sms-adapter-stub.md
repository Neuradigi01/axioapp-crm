# Step 12 — SMS adapter stub + DLT fields

**Goal:** Add the SMS channel to the editor as a sub-form with DLT (Distributed Ledger Technology — India TRAI compliance) capture fields. Register a stub `SMSAdapter` in the conversations adapter registry. Actual SMS transport (Gupshup / MSG91 / Kaleyra) is deferred to a future SMS-channel track.
**Status:** COMPLETED
**Depends on:** Steps 1-8 (module live + editor). Steps 9 + 10 (central tables populated). Step 11 (campaigns generic).

---

## Scope

In-scope:
- Migration `<ts>_sms_dlt_templates.py`:
  - `tbl_sms_dlt_templates` — polymorphic extension for SMS-specific DLT fields. Columns: id, org_id, message_template_id FK CASCADE, dlt_entity_id text, dlt_template_id text, dlt_content_category enum (`transactional|promotional|service_explicit|service_implicit`), dlt_header text (sender id / header — 6-char alphanumeric), dlt_principal_entity_id text, dlt_template_status enum (`registered|pending|rejected`), dlt_registered_at, dlt_rejection_reason. Unique `(org_id, dlt_template_id)` where `dlt_template_id IS NOT NULL`.
  - RLS + indexes.
- `core/templates/sms_extension.py`:
  - `SMSDLTTemplate` SQLAlchemy model.
  - `get_dlt_metadata(template_id)` / `set_dlt_metadata(template_id, payload, user_id)` service functions.
- `core/conversations/adapters/sms.py`:
  - `SMSAdapter` implementing the `ChannelAdapter` Protocol. `send()` raises `SMSNotConfigured` until a provider is wired (acts as a clear marker — UI lists SMS as a usable template channel but campaign launch with SMS gracefully refuses with "Configure an SMS provider in Settings → Integrations").
  - `parse_webhook()` raises `NotImplementedError` — no inbound SMS until a provider track.
  - Registers with the channel registry under `ConversationChannel.sms`.
- Frontend:
  - `APP/.../core/templates/editor/sms-form.component.{ts,html}`:
    - Body textarea with char counter (160 chars per SMS segment; show segment count beyond that — 160 / 306 / 459 …).
    - DLT entity ID input.
    - DLT content category dropdown.
    - DLT header / sender ID input (uppercase, max 6 chars).
    - DLT template ID input (filled after Owner manually registers with DLT portal; UI clearly states "Submit via your DLT portal first, then enter the approved template ID here").
    - Optional `{{1}} / {{2}}` style positional variables (DLT convention).
  - SMS sub-form mounted in `template-editor.page.ts`.
  - List page + status badge support SMS channel chip + external_status badge ("Registered with DLT" / "Pending DLT").

Out of scope:
- Provider OAuth / API client (Gupshup / MSG91 / Kaleyra — future track).
- Actual SMS send.
- Inbound SMS webhook.
- DLT portal submission from inside the CRM (DLT portals are TRAI-mandated external; manual ID capture is the standard CRM pattern).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_sms_dlt_templates.py` | **NEW** |
| `API/src/app/core/templates/sms_extension.py` | **NEW** — SMSDLTTemplate model + service |
| `API/src/app/core/templates/router.py` | edit — `GET/PATCH /templates/{id}/sms-metadata` endpoints |
| `API/src/app/core/conversations/adapters/sms.py` | **NEW** — stub adapter |
| `API/src/app/core/conversations/models.py` | edit — confirm `sms` already in `ConversationChannel` enum (it is) |
| `APP/src/app/features/user/core/templates/editor/sms-form.component.ts` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/sms-form.component.html` | **NEW** |
| `APP/src/app/features/user/core/templates/editor/template-editor.page.ts` | edit — wire SMS sub-form when channel=sms |
| `API/tests/templates/test_sms_extension.py` | **NEW** |

**~9 files. ~450 lines.**

## Plan

0. **Data-access layer** (project convention):
   - `core/templates/data_access/sms_dlt.py` (NEW sub-file) holds DLT-extension reads — `get_dlt_metadata(template_id)` + `find_by_dlt_template_id(...)`.
   - `__init__.py` re-exports the new helpers alongside the existing `templates` + `versions` ones.
   - DLT-metadata set/update writes stay in `core/templates/sms_extension.py` (service-side).
1. Migration: new extension table with RLS.
2. SMS extension model + DLT capture service.
3. Stub adapter registered with the channel registry.
4. Editor sub-form: body textarea + DLT fields + char counter + segment counter.
5. List page: SMS row renders correctly with status badges.
6. Tests: DLT metadata CRUD, char counter math (160 → 1 segment, 161 → 2, 306 → 2, 307 → 3), stub adapter raises on send.

## DB changes / migrations

One migration: new `tbl_sms_dlt_templates` extension table with RLS + index.

## Tests

6 pytest cases:
- DLT metadata round-trip — set + get matches.
- DLT content category enum rejects invalid values.
- Stub adapter raises `SMSNotConfigured` on send.
- Stub adapter registered for `ConversationChannel.sms`.
- Campaign with SMS template fails gracefully with the "configure provider" message.
- SMS template counts variables correctly for char calculation.

## Smoke

```
1. /user/templates/new → channel=SMS → SMS sub-form mounts with body + DLT fields.
2. Type a 200-char body → counter shows "2 segments".
3. Save Draft → DLT entity ID + template ID + category persist.
4. List page → SMS chip + "Pending DLT" badge.
5. Try to create a campaign with this template → reaches the dispatch stage → "SMS provider not configured" error surfaced to operator.
```

## Risks

- DLT content category overlap with template category (marketing / transactional) — they are distinct concepts. Marketing/transactional is OUR internal classification; DLT category is TRAI's. Stored separately.
- SMS char encoding (GSM-7 vs UCS-2) — counter uses simple byte-length math at v1; precise encoding-aware count is a polish step. Acceptable.

## Self-check (10 rules)

`core/templates/sms_extension.py` is in core. ✓ org_id + RLS. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar already registered. Permissions: `templates.read/write` cover SMS too. pack.yaml untouched. ✓ 9 files / ~450 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 12 — SMS adapter stub + DLT fields
Files: 9
Verify: SMS sub-form usable + DLT fields captured + stub adapter registered + clear "provider not configured" surface on send attempt.
Tests: 6 pytest cases.
Awaiting "proceed".
```
