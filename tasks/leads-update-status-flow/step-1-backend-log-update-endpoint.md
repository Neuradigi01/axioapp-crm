# Step 1 — Backend: `POST /leads/{id}/log-update` atomic endpoint + narrow contact schema

**Goal:** Ship one new endpoint that a rep hits from the Update Status modal. It atomically (single session, single commit) records: optional contact-basics patch, optional stage move, optional source change, always a `note` activity with the remarks text, and optional next-follow-up task. All writes go through DAL functions + `activities.record_in_session()` — never through reused services that commit internally.
**Track:** Leads — Update Status Flow
**Status:** Pending
**Depends on:** README D1–D10; activities/service.py `record_in_session()`; move_card DAL; tasks DAL.

---

## Scope

In-scope:

- New Pydantic schemas: `FollowUpContactBasics` (narrow: only `full_name?`, `phone?`, `email?`), `NextFollowUpSpec` (`due_at`, `followup_type`), `LogUpdateRequest`.
- New service `log_update_for_lead()` in `leads/service.py` — the atomic write path.
- New DAL helpers in `leads/data_access.py` for the pieces that don't already have one (narrow contact patch on `tbl_contacts`, direct `tbl_tasks` insert scoped to a lead).
- New router endpoint `POST /api/v1/leads/{lead_id}/log-update` in `leads/router.py`, gated by `leads.write` + conditionally requires `contacts.write` (when `contact_basics` present).
- Rate-limit weight = 3 on the existing per-user leads-write bucket.
- Pytest suite pinning the 12 assertions listed under **Tests**.

Out of scope:

- No changes to `move_stage_for_lead`, `contacts.update_contact`, or `tasks.service.create_task`. Their internal commits would break atomicity if reused — this endpoint inlines the DAL calls instead.
- No frontend. Step 3 wires the modal.
- No new leads filter surface. Step 2.
- No new activity type. `note` and `status_change` are the only types written.
- No new task fields. Existing `TaskFollowupType` (call/whatsapp/email/document/meeting/other) is what the frontend picker exposes.

## DB changes / migrations

**None.** Every write lands in existing tables (`tbl_leads`, `tbl_contacts`, `tbl_activities`, `tbl_tasks`).

## Files to touch

| File | Action |
|---|---|
| [`API/src/app/core/leads/schemas.py`](../../API/src/app/core/leads/schemas.py) | modified — add `FollowUpContactBasics`, `NextFollowUpSpec`, `LogUpdateRequest`, `LogUpdateResponse` |
| [`API/src/app/core/leads/data_access.py`](../../API/src/app/core/leads/data_access.py) | modified — add `patch_contact_basics_narrow(session, contact_id, org_id, patch)` and `insert_lead_task(session, lead_id, org_id, title, due_at, followup_type, assigned_to_id)`; add `contact_lead_count(session, contact_id, org_id)` for the shared-contact guard |
| [`API/src/app/core/leads/service.py`](../../API/src/app/core/leads/service.py) | modified — add `log_update_for_lead()` |
| [`API/src/app/core/leads/router.py`](../../API/src/app/core/leads/router.py) | modified — new `POST /{lead_id}/log-update` endpoint |
| `API/tests/test_leads_log_update.py` | created |

**5 files, ~350 LOC.** Inside rule-8.

## Plan

1. **Schemas.** Define the three request models. `FollowUpContactBasics` has ONLY `full_name: str | None`, `phone: str | None`, `email: EmailStr | None`. `NextFollowUpSpec` has `due_at: datetime` (validated: `now - 365d ≤ v ≤ now + 5*365d`) + `followup_type: TaskFollowupType`. `LogUpdateRequest`:
   ```python
   class LogUpdateRequest(BaseModel):
       if_current_stage: str  # optimistic guard, required
       contact_basics: FollowUpContactBasics | None = None
       pipeline_stage: str | None = None  # target stage; server derives from_stage
       source: LeadSource | None = None
       remarks: str = Field(min_length=1, max_length=2000)
       next_follow_up: NextFollowUpSpec | None = None
       model_config = ConfigDict(extra="forbid")  # reject unknown fields
   ```
2. **DAL helpers** in `leads/data_access.py`:
   - `patch_contact_basics_narrow(session, *, contact_id, org_id, full_name, phone, email)` — issues `UPDATE tbl_contacts SET full_name=COALESCE(:v,full_name)... WHERE id=:id AND org_id=:org` (org-scoped by second clause). No commit.
   - `insert_lead_task(session, *, org_id, lead_id, title, due_at, followup_type, assigned_to_id, created_by_id)` — `INSERT INTO tbl_tasks (...) RETURNING id`. No commit.
   - `contact_lead_count(session, *, contact_id, org_id) -> int` — one `SELECT COUNT(*) FROM tbl_leads WHERE contact_id=:c AND org_id=:o AND deleted_at IS NULL`.
3. **Service** `log_update_for_lead(session, *, lead_id, caller, payload)`:
   1. `lead = await get_lead(session, lead_id)`; `if lead is None or lead.org_id != caller.org_id: 404`. (Attacker HIGH #3 defence-in-depth.)
   2. Ownership visibility: if caller lacks `users.read` and `lead.assigned_to_id != caller.legacy_uuid` → 404 (mirrors `get_lead_visible_to`).
   3. `if payload.if_current_stage != lead.pipeline_stage: 409` with body `{"detail": "stage_drifted", "current_stage": lead.pipeline_stage}`.
   4. If `payload.contact_basics`:
      - `require_permissions("contacts.write")` — done in router, not here.
      - `count = await contact_lead_count(session, contact_id=lead.contact_id, org_id=caller.org_id)`; if `count > 1` → 422 `{"detail": "contact_shared", "lead_count": count}`.
      - `await patch_contact_basics_narrow(session, ...)`.
   5. If `payload.pipeline_stage` and `payload.pipeline_stage != lead.pipeline_stage`:
      - Validate target stage belongs to the leads pipeline (reuse `pipelines._da.card_table_pipeline_check` or inline the SELECT — do NOT call `move_stage_for_lead` because it commits).
      - Call `pipelines._da.update_card_pipeline_stage(session, table="tbl_leads", card_id=lead_id, to_key=payload.pipeline_stage)` — this is what `move_card` uses internally; no commit.
      - Insert `status_change` activity via `activities.record_in_session(session, org_id=..., entity_type="lead", entity_id=lead_id, type=ActivityType.status_change, payload={"pipeline":"leads", "from":<server-read from_stage>, "to":payload.pipeline_stage}, user_id=caller.legacy_uuid)`.
      - If target stage `is_won` → set `lead.won_at = now()` if null; if `is_lost` → set `lead.lost_at = now()` if null. Update `lead.status` to the derived `LeadStatus` (matches `move_stage_for_lead` line 1001-1007 logic — copy inline here).
   6. If `payload.source and payload.source != lead.source`: `lead.source = payload.source`.
   7. Always: insert `note` activity via `activities.record_in_session(...)` with `payload={"text": payload.remarks}`.
   8. If `payload.next_follow_up`: `await insert_lead_task(session, org_id=..., lead_id=lead_id, title=f"Follow up: {payload.remarks[:80]}", due_at=..., followup_type=..., assigned_to_id=lead.assigned_to_id or caller.legacy_uuid, created_by_id=caller.legacy_uuid)`.
   9. `await session.commit()`.
   10. `await session.refresh(lead)` and return.
4. **Router** `POST /{lead_id}/log-update`:
   - Base gate: `Depends(require_permissions("leads.write"))`.
   - Inside handler: if `payload.contact_basics is not None`, additionally require `contacts.write` on the caller (small helper — mirror existing conditional-permission pattern). If missing → 403.
   - Rate-limit: use existing `Depends(rate_limit_leads_write(weight=3))` if that shape exists, else add a `weight=3` param on the existing bucket helper.
   - Return the refreshed `LeadOut` + the created `next_follow_up_task_id` (nullable) in a `LogUpdateResponse`.
5. **Layered-arch pin-test.** The existing `API/tests/test_layered_architecture_convention.py` already fails CI if `service.py` runs SQL directly. Our service only calls DAL helpers + `activities.record_in_session()` (which is legally a service-in-session helper, not raw SQL) — verify this passes before shipping.

## Tests

`API/tests/test_leads_log_update.py`:

1. **Happy path — all four writes atomic.** POST with contact_basics + pipeline_stage + remarks + next_follow_up → 200. Assert: contact row patched, lead row's stage/status/source updated, one `note` + one `status_change` activity row, one `tbl_tasks` row with `related_entity_type='lead'`.
2. **Rollback on downstream failure.** Force `insert_lead_task` to raise (patch with a monkeypatch). Assert: none of the contact / lead / activity rows appear — full rollback.
3. **Pin-test — no reused-service commits.** Grep-assert that `log_update_for_lead` body does NOT contain the substrings `move_stage_for_lead`, `update_contact(`, `create_task(`. Rationale: those services commit internally; any future refactor that reintroduces them breaks atomicity.
4. **Optimistic stage guard.** POST with `if_current_stage='old-stage'` when the DB has `new-stage` → 409 with `current_stage` in body.
5. **Narrow contact schema — extra fields rejected.** POST with `contact_basics={"assigned_to_id":"<uuid>"}` → 422 (Pydantic `extra=forbid`).
6. **Shared contact guard.** Given contact linked to 2 leads, POST with `contact_basics` present → 422 `{"detail":"contact_shared", "lead_count":2}`.
7. **Cross-org defence.** Owner in org A posts to a lead in org B (id guessed) → 404.
8. **Ownership visibility.** Junior rep without `users.read` posts to a colleague's lead → 404.
9. **`from_stage` cannot be forged.** POST includes a garbage `from_stage` in the payload → schema rejects (extra=forbid); status_change activity row's `payload.from` always equals the DB's actual prior stage.
10. **`due_at` bounds.** `due_at = now() - 400d` or `now() + 6*365d` → 422.
11. **`contacts.write` gate.** Caller with `leads.write` but no `contacts.write` and contact_basics present → 403.
12. **Remarks-only no-change post.** POST with just `if_current_stage` + `remarks` (no other fields) → 200; exactly one new `note` activity row, no task, no status_change, no contact patch.

## Smoke

```powershell
# Migrations up (no new migrations, but verify head)
docker exec crm-api-1 alembic upgrade head

# Restart to pick up new endpoint
docker restart crm-api-1

# Curl the new endpoint (Ajay's Workspace org, use the Neuradigi lead id from Overview URL)
$token = "<owner JWT>"
$leadId = "<neuradigi-lead-uuid>"
curl -X POST http://localhost:8000/api/v1/leads/$leadId/log-update `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"if_current_stage": "proposal", "remarks": "smoke test note", "next_follow_up": {"due_at": "2026-08-19T10:00:00Z", "followup_type": "call"}}'
# Expect 200 + refreshed lead + next_follow_up_task_id.

# Verify in DB (via docker exec + a small python one-liner)
docker exec crm-api-1 python -c "import asyncio; from sqlalchemy import text; from src.app.shared.db import async_session; asyncio.run((lambda: (lambda s: [print(r) for r in s.execute(text(\"SELECT type,payload FROM tbl_activities WHERE entity_type='lead' AND entity_id='$leadId' ORDER BY created_at DESC LIMIT 3\"))])())())"

# Pytest (run AFTER the user confirms; per memory: pause before pytest — ~12min run)
# docker exec crm-api-1 pytest tests/test_leads_log_update.py -v
```

## Risks

- **Duplicating `move_stage_for_lead`'s status-sync logic** (won/lost stamp + LeadStatus derivation) inline in this service is a copy-paste risk. Mitigation: extract the pure derivation (stage → status + timestamps) into a shared helper in `leads/service.py` and call it from both places. Small refactor — do it in this step.
- **Reused-service drift.** If someone later "cleans up" this service to call `move_stage_for_lead()` or `contacts.update_contact()`, atomicity silently breaks. Pin-test #3 catches this.
- **`contacts.write` conditional check** is a slight departure from the "one permission per endpoint" pattern used elsewhere. Alternative: split into two endpoints — but that breaks the atomicity claim. Keeping the conditional check.
- **Weight=3 rate limit** assumes the existing bucket helper accepts a `weight` kwarg. If not, add it in this step (single-line change to the helper).

## Rollback

Revert the four `.py` files. No DB migration to reverse.
