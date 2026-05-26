# Step 6 — Backend: cross-source dedup + lead routing (round-robin)

**Goal:** Centralise lead-ingestion side-effects. Every new lead (manual, bulk, widget, Google, Meta) flows through the same dedup check and assignment logic. Dedup: if a contact with matching phone/email already has an open lead in the same org, append a new activity to that lead and skip lead creation. Routing: round-robin assign across users with the `leads.own` permission, or honour a per-org routing rule.
**Track:** Ad Integrations
**Status:** COMPLETED
**Depends on:** Manual Lead Entry Step 1 (`lead.source` enum), Bulk Import Step 2 (`dedup.py` foundation), Embeddable Widget Step 2 (attribution column), Steps 3 + 5 (ad webhook tasks call into this).

---

## Scope

In-scope:

- New migration: add `leads.assigned_to UUID REFERENCES users(id) NULL` if not already present. Add `lead_routing_config` JSONB column on `organizations` (or sibling table; mirror existing per-org settings pattern).
- `core/leads/dedup.py` — extended from the bulk-import version:
  - `find_open_lead_for_contact(org_id, contact_id) -> Lead | None` — returns the most recent open lead (status not "closed_won"/"closed_lost") for this contact in the org.
  - Refactor existing functions if needed.
- `core/leads/routing.py`:
  - `pick_assignee(org_id, source) -> User | None`.
  - Strategies:
    - `round_robin`: keep a counter per org in `lead_routing_state`; pick next user with `leads.own` permission.
    - `sticky_by_source`: future strategy (e.g. all Meta leads to user X); skeleton only — v1 ships round-robin.
  - Returns `None` if no eligible users; lead remains unassigned and surfaces in an "Unassigned" filter on the leads page.
- `core/leads/ingest.py` — a thin shared service that all four channels call:
  - `ingest(org_id, source, contact_data, lead_data, attribution, actor_user_id) -> IngestResult`
  - Logic:
    1. Find-or-create contact (dedup on phone + email — existing logic).
    2. Find open lead for that contact. If exists:
       - Append an activity on the existing lead: `New touchpoint via {source} — {summary}`.
       - Return `IngestResult(action="merged", lead_id=existing.id, contact_id=contact.id)`.
    3. Else, create a new lead with `assigned_to = pick_assignee(...)`.
       - Return `IngestResult(action="created", lead_id=new.id, contact_id=contact.id, assignee=user.id)`.
  - Emits one of `lead.created` (existing) or new `lead.ingested_merged_to_existing` audit event.
- Refactor the four channels to call `leads.ingest.ingest(...)` instead of their per-channel `LeadService.create()`:
  - Manual entry: lead form modal endpoint.
  - Bulk import Celery task.
  - Widget submission service.
  - Google + Meta webhook tasks.
- Settings endpoint stubs `GET /api/v1/leads/routing-config` and `PUT /...` (config persisted; v1 only exposes `strategy: "round_robin"` — no real choices, but the surface is there for the frontend in Step 8).
- Tests for dedup, routing, end-to-end ingestion through each channel.

Out of scope:

- Custom routing rules (by geography, store, ad campaign) — Settings UI surfaces the slot but the engine only supports round-robin.
- Re-balancing (moving leads from one rep to another) — separate task.
- Lead status state machine changes.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_assigned_to_and_routing_config.py` | created |
| `api/src/app/core/leads/models.py` | modified — `assigned_to: Mapped[UUID \| None]` |
| `api/src/app/core/leads/dedup.py` | modified — add `find_open_lead_for_contact` |
| `api/src/app/core/leads/routing.py` | created |
| `api/src/app/core/leads/ingest.py` | created |
| `api/src/app/core/leads/router.py` | modified — refactor `POST /leads` to call `ingest.ingest(...)` |
| `api/src/app/core/leads/imports/tasks.py` | modified — refactor to call `ingest.ingest(...)` |
| `api/src/app/core/embed/submissions.py` | modified — refactor to call `ingest.ingest(...)` |
| `api/src/app/core/integrations/google/tasks.py` | modified — refactor to call `ingest.ingest(...)` |
| `api/src/app/core/integrations/meta/tasks.py` | modified — refactor to call `ingest.ingest(...)` |
| `api/src/app/core/audit/events.py` | modified (small) — declare `LEAD_INGESTED_MERGED_TO_EXISTING` |
| `api/src/app/core/tenants/router.py` (or wherever org settings live) | modified (small) — routing-config endpoints |
| `api/tests/test_lead_ingest.py` | created — end-to-end through each channel |

**13 files, 1 migration.** Marginally over rule-8. The refactor of four channels into one shared service is the core work; splitting would break the refactor's atomicity. Implementer can split into 6a (introduce `ingest.py` + migration + routing) and 6b (refactor each channel + tests) if needed.

## Plan

1. Migration: add `assigned_to`, `routing_config` JSONB on org, `lead_routing_state` table (for round-robin counter):
   ```sql
   CREATE TABLE lead_routing_state (
       org_id UUID PRIMARY KEY REFERENCES organizations(id),
       next_assignee_index INT NOT NULL DEFAULT 0,
       updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
   );
   ```
2. Implement `routing.pick_assignee`:
   - Load eligible users: those in this org with `leads.own` permission.
   - If none → return None.
   - Atomic increment `lead_routing_state.next_assignee_index` via `UPDATE ... RETURNING`.
   - Modulo by user count → pick that user.
3. Implement `dedup.find_open_lead_for_contact`:
   - `SELECT * FROM leads WHERE org_id=? AND contact_id=? AND status NOT IN ('closed_won','closed_lost') ORDER BY created_at DESC LIMIT 1`.
4. Implement `ingest.ingest`:
   - Find-or-create contact (existing).
   - Call `find_open_lead_for_contact`. Hit → create an activity on it (call existing `ActivityService.create`), return `merged`.
   - Miss → call `pick_assignee`, create lead with `assigned_to=...`, `source=...`, `attribution=...`, return `created`.
   - Audit event accordingly.
5. Refactor each channel's call site to use `ingest.ingest(...)`. Keep the existing `LeadService.create` for direct DB-only writes (tests, seeds), but the four channels no longer call it directly.
6. Settings endpoints — stub. v1 returns `{strategy: "round_robin"}` and accepts the same on PUT (no-op for now).
7. Tests:
   - Each channel → ingest → contact + lead created with right `source`, `assigned_to` populated round-robin.
   - Second submission with same phone → no new lead; existing lead has a new activity.
   - Round-robin distribution: 6 submissions across 3 users → 2 each.

## Tests

`api/tests/test_lead_ingest.py`:

- **Manual create routes through ingest:** POST /leads → result has `assigned_to` set.
- **Round-robin distribution:** 3 sales users → 9 submissions → each user gets 3 leads.
- **Dedup against open lead:** create contact + lead. Submit a widget form with the same phone → no new lead; the existing lead's activity timeline has a new "Touchpoint via widget" entry; ingest returns `merged`.
- **Dedup respects closed leads:** if the existing lead is `closed_won`, a new submission creates a NEW lead (closed leads don't block).
- **Channel parity:** end-to-end test that runs (a) manual POST (b) bulk import row (c) widget submission (d) Google webhook (mocked) (e) Meta webhook (mocked) — each produces a lead with the correct `source` and a non-null `assigned_to`.
- **No eligible users:** if no user in the org has `leads.own` permission → lead created with `assigned_to=NULL`; `pick_assignee` does not raise.
- **Routing state is atomic:** simulate 100 concurrent submissions; assignment distribution is balanced (within ±1 of uniform).

## Smoke

```powershell
# Run all the existing per-channel smokes (manual entry, bulk import, widget, google, meta).
# After each, check that the new lead has a non-null assigned_to (visible on the leads kanban).

# Submit a manual lead with phone +919876543210.
# Then submit a widget form with the same phone.
# Confirm: only one lead exists for that contact, with an extra activity from the widget submission.

# Round-robin sanity: create 3 sales users (sales1, sales2, sales3).
# Submit 9 leads via /leads. Verify 3 each in the leads kanban (filter by assignee).
```

## Risks

- **Refactor blast radius:** changing four channels at once is risky. Land Step 6 only after Steps 1–5 of *every other track* are individually verified working; then refactor.
- **Activity-on-merge UX:** the "Touchpoint via {source}" activity needs a clear shape that surfaces on the lead detail page. Make sure the existing activities timeline renders it well (no template change needed if it uses a generic `type + summary` shape).
- **Round-robin counter contention:** atomic UPDATE RETURNING avoids races; at thousands of writes/sec this might become a hotspot, but our scale is ≤ 100 writes/min/org for the foreseeable future. Fine.
- **`leads.own` permission semantics:** "eligible to own a lead" must be a permission distinct from "can view leads". If today there's only `leads.view`/`leads.create`/`leads.edit`, this step introduces `leads.own` as part of the permissions registry — small addition. Confirm at implementation time and add to the migration if needed.
- **Routing config schema is a stub:** v1 only does round-robin but the JSONB column accommodates future rules. Document that `strategy` is the only valid key for v1.

## Rollback

Reverse migration (drops `assigned_to`, `routing_config`, `lead_routing_state`). Revert channel refactors — each goes back to calling `LeadService.create` directly. Tests must be re-run after rollback to confirm. Existing leads retain their `assigned_to` column values until migration rolls back — at that point those values are lost.
