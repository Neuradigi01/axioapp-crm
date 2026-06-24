# Step 4 — Internal review workflow

**Goal:** State machine `draft → in_review → approved → published → archived` (with `rejected` returning to draft) + workflow endpoints + org-level mandatory-review toggle. Templates can only be used in campaigns / triggers when `internal_status='published'` AND `external_status in ('n_a', 'approved')`.
**Status:** Pending
**Depends on:** Step 1 (schema), Step 2 (service), Step 3 (router + perms).

---

## Scope

In-scope:
- `core/templates/workflow.py`:
  - State machine: defines allowed transitions and reviewer-only transitions.
  - `submit_for_review(org_id, template_id, user_id)` → `draft → in_review`.
  - `approve(org_id, template_id, reviewer_id, note?)` → `in_review → approved`. Reviewer ≠ author check (configurable via org setting `template_review_self_approve_allowed BOOL`, default false).
  - `reject(org_id, template_id, reviewer_id, note)` → `in_review → draft`. Note required.
  - `request_changes(org_id, template_id, reviewer_id, note)` → `in_review → draft` (same effect as reject; semantic distinction surfaced in audit + UI).
  - `publish(org_id, template_id, user_id)` → `approved → published`. Pre-check: `external_status in ('n_a', 'approved')`.
  - `archive(org_id, template_id, user_id)` → any → `archived`.
  - Every transition writes one row to `tbl_message_template_reviews` and emits a `templates.<action>` audit event.
- `core/templates/router.py` extended with five endpoints:
  - `POST /api/v1/templates/{id}/submit` — author submits draft. Gated on `templates.write`.
  - `POST /api/v1/templates/{id}/approve` — reviewer approves. Gated on `templates.review`.
  - `POST /api/v1/templates/{id}/reject` — reviewer rejects. Gated on `templates.review`.
  - `POST /api/v1/templates/{id}/publish` — author or reviewer publishes. Gated on `templates.publish`.
  - `POST /api/v1/templates/{id}/archive` — gated on `templates.write`.
- Org-level setting `template_review_mandatory BOOL DEFAULT false` on `tbl_organizations` — when true, author cannot publish without going through `in_review → approved` first; when false, author can publish directly from `draft` (skips `in_review`). Surfaced in `GET/PATCH /api/v1/settings/general`.
- Migration `<ts>_org_template_review_settings.py`:
  - Adds `template_review_mandatory BOOL DEFAULT false` and `template_review_self_approve_allowed BOOL DEFAULT false` columns to `tbl_organizations`.

Out of scope:
- External-provider workflow (Meta WA submission, SMS DLT) — Steps 9 + 12 + 14.
- UI for review actions (Step 8).
- Notification on `in_review` to reviewers — handled later via `tasks/automation-engine/` triggers (out of this track).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/templates/workflow.py` | **NEW** |
| `API/src/app/core/templates/service.py` | edit — call into workflow for state changes |
| `API/src/app/core/templates/router.py` | edit — five new endpoints |
| `API/src/app/core/templates/schemas.py` | edit — `WorkflowActionPayload {note?}` |
| `API/alembic/versions/<ts>_org_template_review_settings.py` | **NEW** |
| `API/src/app/core/tenants/models.py` | edit — two new columns on Organization |
| `API/src/app/core/tenants/schemas.py` | edit — expose two new fields on OrgSettings shape |
| `API/src/app/core/tenants/router.py` | edit — accept the two fields in settings PATCH |
| `API/tests/templates/test_workflow.py` | **NEW** |

**~9 files. ~500 lines.**

## Plan

1. Migration: two columns on `tbl_organizations`.
2. `workflow.py` — pure state-transition functions. Each validates current state + writes the review row + emits audit + returns updated template.
3. Wire workflow functions into `service.py` so callers go through service, not workflow directly.
4. Router endpoints: thin wrappers calling service.
5. `tenants/` extension: surface the two settings via the existing org-settings endpoint.
6. Tests cover every legal + illegal transition + permission gating + self-approve guard + mandatory-review override.

## DB changes / migrations

One migration adding two `bool` columns to `tbl_organizations`. Reversible.

## Tests

12-15 pytest cases:
- Every legal transition (5 transitions).
- Every illegal transition rejected with the right exception.
- `approve` blocked when reviewer == author and `self_approve_allowed=false`.
- `approve` allowed when reviewer == author and `self_approve_allowed=true`.
- `publish` blocked when `external_status='pending'`.
- `publish` allowed when `external_status='approved'`.
- `publish` from `draft` works when `template_review_mandatory=false`.
- `publish` from `draft` blocked when `template_review_mandatory=true`.
- Review-row written on every transition with correct action + note + reviewer.
- Audit event emitted for every transition.
- `archive` from any state succeeds.

## Smoke

```
1. POST /api/v1/templates {name, channel=email, body, subject} → 200 draft.
2. POST /templates/{id}/submit → 200; internal_status=in_review.
3. POST /templates/{id}/approve as the same user → 403 (self-approve disallowed by default).
4. As a different reviewer with templates.review perm: POST /templates/{id}/approve → 200; internal_status=approved.
5. POST /templates/{id}/publish → 200; internal_status=published.
6. PATCH /templates/{id} {body: "new"} → 409 TemplateLocked.
7. POST /templates/{id}/archive → 200; internal_status=archived.
8. PATCH /api/v1/settings/general {template_review_mandatory: true} → 200.
9. New draft → POST /publish directly → 409 (must go through review first).
```

## Risks

- Audit events flooding the bus during bulk operations — none expected at v1 scale; revisit if observed.
- Reviewer ≠ author check uses `created_by_user_id` snapshot at template creation; if the original author later transfers ownership, the check still uses the original author. Acceptable + documented in the workflow module docstring.

## Self-check (10 rules)

`core/templates/`. ✓ org_id on every transition. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar (Step 5). Permission registry already extended in Step 3. pack.yaml untouched. ✓ 9 files / ~500 lines — at the upper bound, justified by tests + cross-module touch points. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 4 — Internal review workflow
Files: 9
Verify: full state machine + org-level mandatory-review + self-approve guard + reviewer trail.
Tests: 15 pytest cases.
Awaiting "proceed".
```
