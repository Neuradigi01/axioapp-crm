# Step 3.13 — Reviews: backend

**Goal:** `reviews` table with configurable `source` (furniture pack defaults to `google`). Review-request automation hook (will integrate with Campaigns later).
**Phase:** 3
**Depends on:** 2.4
**Status:** Pending

## Scope
**In-scope:**
- Model `Review` (TenantScoped): id, org_id, source (text — `google`, `facebook`, `internal`, etc.), source_id (external review id, optional), contact_id, rating (1–5), text, reply_text, replied_at, replied_by_id, status (pending_reply/replied/escalated), tags text[], created_at.
- Migration + RLS + indexes (`org_id, rating`, `org_id, source`).
- Endpoints: `/reviews` CRUD, `POST /reviews/{id}/reply`, `POST /reviews/{id}/escalate`.
- Stats endpoint `/reviews/stats` — distribution, average, response rate, alerts (≤3 stars in last 7 days).
- Permission: `reviews.read`, `reviews.write`.

**Out of scope:**
- Pulling from Google API — later (Phase 5/6 integrations).
- Frontend — 3.14.
- Auto-request after delivery — 5.11.

## Files to touch
- `api/app/core/reviews/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0020_reviews.py` (created)
- `api/app/main.py` (modified)

## Plan
1. Model + migration.
2. Endpoints + stats query (group by rating, avg, count where created_at > now-7d AND rating <=3).
3. Reply persists `reply_text` + `replied_at`/`replied_by_id`.

## Tests to add
- `tests/test_reviews_crud.py`
- `tests/test_reviews_stats.py`

## Verification checklist
**Backend:**
- create review with rating=2 → appears in alert count.
- reply → review.status becomes `replied`.

## Self-check (10 rules)
- [ ] Source is configurable (rule 3 spirit — engine generic).

## Stop & report
Await "proceed" before Step 3.14.
