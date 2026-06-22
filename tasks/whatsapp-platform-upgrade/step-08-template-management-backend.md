# Step 8 — Template management backend (CRUD + Meta submit + status sync)

**Goal:** Promote `tbl_whatsapp_templates` from a read-only Meta-sync table to a full Core CRM source-of-truth surface. Backend endpoints for create / edit / submit-for-approval / duplicate / delete templates. Webhook handles approval / rejection status updates.
**Status:** COMPLETED
**Depends on:** Phase 1 complete (ES-connected org with token authorized for template management).

---

## Scope

In-scope:
- Schema extension to existing `tbl_whatsapp_templates`:
  - `body_components JSONB` (header / body / footer / buttons array, matching Meta's spec)
  - `meta_template_id VARCHAR(64) NULL`
  - `submission_status` enum: `draft` / `pending_review` / `approved` / `rejected` / `paused` / `disabled`
  - `rejection_reason TEXT NULL`
  - `submitted_by_user_id` FK NULL, `submitted_at` TIMESTAMPTZ NULL
- Endpoints under existing `/api/v1/whatsapp/templates`:
  - `GET /` — list with filters (status, category, language)
  - `POST /` — create draft (Meta call deferred until submit)
  - `PATCH /{id}` — edit (only when status in {draft, rejected})
  - `POST /{id}/submit` — POST to `/{waba_id}/message_templates` Meta endpoint
  - `DELETE /{id}` — delete draft locally; if previously submitted, also call Meta delete
  - `POST /{id}/duplicate` — clone with " (copy)" suffix
- Webhook subscription extended for `message_template_status_update` event → updates `submission_status` + `rejection_reason`.
- Existing read-only sync extended to backfill `meta_template_id` for templates already present at Meta (idempotent).
- New permission keys registered in registry: `whatsapp.templates.read`, `whatsapp.templates.write`, `whatsapp.templates.submit`.

Out of scope:
- Frontend wizard — Step 9.
- Per-template performance — Step 10.

## Files to touch

| File | Action |
|---|---|
| [`API/src/app/core/integrations/whatsapp/models.py`](API/src/app/core/integrations/whatsapp/models.py) | Schema extensions |
| `API/alembic/versions/<ts>_whatsapp_templates_extended.py` | **NEW** migration |
| `API/src/app/core/integrations/whatsapp/templates_router.py` | **NEW** route module |
| `API/src/app/core/integrations/whatsapp/templates_service.py` | **NEW** service layer |
| [`API/src/app/core/integrations/whatsapp/webhook.py`](API/src/app/core/integrations/whatsapp/webhook.py) | Handle `message_template_status_update` |
| [`API/src/app/core/integrations/whatsapp/module.py`](API/src/app/core/integrations/whatsapp/module.py) | Register new permission keys |
| `API/tests/integrations/test_whatsapp_templates.py` | **NEW** |

**~7 files. ~500 lines.**

## Plan

1. Migration: extend table; backfill `submission_status` from existing Meta-synced rows.
2. Service layer wraps Meta Graph calls (reuse `meta_graph_client.py` from Step 2).
3. Validation rules: body 1024 chars max; header text 60 chars max; footer 60 chars max; buttons mix (quick reply OR CTA, never both) per Meta spec; variable count must match sample values supplied.
4. Permission registration via module descriptor.
5. Webhook: on status update event, lookup by `meta_template_id`, update status + rejection_reason, audit-log the transition.
6. Tests cover: create draft → submit → simulated webhook approval → status flips; rejection path; edit blocked on approved templates; delete-with-Meta-call path.

## DB changes / migrations

```sql
ALTER TABLE tbl_whatsapp_templates
  ADD COLUMN body_components JSONB,
  ADD COLUMN meta_template_id VARCHAR(64),
  ADD COLUMN submission_status whatsapp_template_status_enum,
  ADD COLUMN rejection_reason TEXT,
  ADD COLUMN submitted_by_user_id UUID REFERENCES tbl_users(id),
  ADD COLUMN submitted_at TIMESTAMPTZ;
CREATE INDEX idx_whatsapp_templates_meta_id ON tbl_whatsapp_templates(meta_template_id);
```

## Tests

8 pytest cases — CRUD + submit + webhook status update + permission gates + idempotent backfill.

## Smoke

```
1. POST /templates with a marketing body → 200 → status=draft.
2. POST /templates/{id}/submit → 200 → Meta receives → status=pending_review + meta_template_id populated.
3. Wait or simulate webhook → status flips approved.
4. PATCH /templates/{id} with body change → 403 (cannot edit approved).
5. POST /templates/{id}/duplicate → new draft with body cloned.
6. DELETE /templates/{id} → calls Meta delete + soft-deletes locally.
7. Sales-Junior without templates.submit permission → 403 on submit.
```

## Risks

- Meta review variability — webhook may take 30s to 24hr. UI handles "pending forever" gracefully.
- Rejected templates' reason often opaque; surface raw Meta message + link to template guidelines.
- Idempotency on backfill: avoid duplicating rows if sync runs twice.

## Self-check (10 rules)

- [ ] `core/integrations/whatsapp/`. ✓
- [ ] org_id + RLS. ✓
- [ ] Custom fields unaffected. ✓
- [ ] Template form spec is fixed (Meta-spec'd, not custom-field-driven). ✓ N/A
- [ ] Module descriptor extension (permission registry). ✓
- [ ] 3 new permission keys registered. ✓
- [ ] pack.yaml untouched. ✓
- [ ] 7 files, ~500 lines. ✓
- [ ] Stop and report. ✓
- [ ] No TODOs. ✓

## Stop & report

```
Step 8 — Template management backend
Files: 7
Verify: full CRUD + submit/approval cycle + permission gates.
Tests: 8 pytest cases.
Migration SQL captured.
Next: Step 9 — template builder UI.
Awaiting "proceed".
```
