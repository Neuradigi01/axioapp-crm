# Step 4.10 — Furniture: Field Operations — backend + frontend

**Goal:** `fp_field_visits` table. Visit scheduling (uses appointments engine). Photo upload + measurement capture. Frontend lists per-staff scheduled/completed visits. Wires into Staff dashboard's Field Operations tab and Staff Portal's Field Visits tab.
**Phase:** 4
**Depends on:** 2.13, 3.4, 4.8
**Status:** Pending

## Scope
**In-scope:**
- Backend:
  - Model `FieldVisit` (`fp_field_visits`, TenantScoped): id, org_id, appointment_id (FK→appointments), purpose (measurement/installation/inspection), custom_order_id (nullable), notes, completed_at, signature_url (nullable).
  - `FieldVisitPhoto` (`fp_field_visit_photos`): id, org_id, visit_id, url, caption, taken_at.
  - Migration + RLS.
  - Endpoints `/api/v1/field-visits` CRUD + photo upload + `POST /field-visits/{id}/complete` (sets completed_at, optionally creates measurements on a linked custom order).
  - Permission `field_visits.read`, `field_visits.write`.
- Frontend:
  - `app/src/app/features/user/packs/furniture/field-ops/` — page with filters (today/upcoming/completed), schedule-visit modal (creates appointment + visit), visit-detail page with photo gallery + complete button.
  - Wire into Staff dashboard Field Operations tab (3.5) and Staff Portal Field Visits tab (3.7) — replace the placeholders.

## Files to touch
- `api/src/app/packs/furniture/modules/field_ops/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0025_fp_field_visits.py` (created)
- `app/src/app/features/user/packs/furniture/field-ops/*` (created)
- `app/src/app/features/user/core/staff/tabs/field-ops.component.ts/.html` (modified — replaces stub)
- `app/src/app/staff-portal/field/field-visits.page.ts/.html` (modified — replaces stub)

## Plan
1. Backend models + migration.
2. Schedule modal creates appointment via core endpoint, then field-visit via pack endpoint, in one frontend transaction.
3. Complete action: optional measurement copy-back to linked custom order.

## Tests to add
- `tests/test_field_visits.py`

## Verification checklist
**Backend/Frontend:**
- schedule a visit → appointment + field_visit created.
- staff portal: shows the visit; complete it → status updates.

## Self-check (10 rules)
- [ ] Pack reuses appointments engine (no duplication).
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 4.11.
