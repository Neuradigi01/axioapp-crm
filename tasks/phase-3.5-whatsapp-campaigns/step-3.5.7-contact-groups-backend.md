# Step 3.5.7 — Contact groups (segments): backend tables + CRUD + audience preview

**Goal:** First-class "Contact group" entity so a campaign can target a saved audience by group name instead of re-building the filter each time. Foundation for the audience builder in 3.5.9.

**Phase:** 3.5
**Depends on:** 1.x (contacts module)
**Status:** ✅ COMPLETED — 62/62 tests pass, 2 tables + 6 routes live

After this step an Owner / Sales Manager can POST `/api/v1/contact-groups` with a name + an optional filter shape (same as `/contacts` query) OR an explicit list of contact ids; campaigns reference the group via `audience_filter.group_id`.

---

## Scope

### In-scope

- **Tables:**
  - `contact_groups`: `id`, `org_id` (TenantScoped), `name`, `description`, `filter_json` (JSONB, nullable — when group is filter-based), `is_dynamic` (boolean — true = filter-based, false = static), `created_by_id`, `created_at`, `updated_at`. UNIQUE(`org_id`, `name`).
  - `contact_group_members`: bridge — `id`, `org_id`, `group_id` (FK), `contact_id` (FK), `added_at`. UNIQUE(`group_id`, `contact_id`). Only populated for **static** groups; dynamic groups resolve on-demand.
- Migration `0064_contact_groups.py` + RLS on both tables.
- Service:
  - `create_group(name, description, is_dynamic, filter_or_ids)` — for dynamic: stores filter; for static: bulk-inserts member rows.
  - `update_group(...)` — name/description/filter editable; member set replaceable for static.
  - `delete_group(id)` — hard delete; campaign rows that reference it via `audience_filter.group_id` see the filter resolve to empty (handled gracefully in 3.5.9).
  - `resolve_group_contacts(group_id) -> list[contact_id]` — dynamic groups run the filter; static groups read members. Returns sorted ids.
  - `preview_audience_size(filter_or_group_id) -> int` — count, no rows. Powers the "X contacts will receive this" line in the campaign modal.
- REST endpoints under `/api/v1/contact-groups`:
  - `GET /` (paginated list)
  - `POST /`
  - `GET /{id}` (with member sample — first 10)
  - `PATCH /{id}`
  - `DELETE /{id}`
  - `POST /preview-size` — body: `{filter_json}` OR `{group_id}` — returns `{count}` (used by audience builder without saving a group)
- Permission: `contacts.write` (existing) for create/edit/delete; `contacts.read` for list/preview.

### Out-of-scope

- Group-membership management UI → 3.5.8.
- Auto-tagging contacts as "imported via X.xlsx" → that's import metadata, separate from groups.

---

## Files to touch

### Created (4)
- `API/alembic/versions/0064_contact_groups.py`
- `API/src/app/core/contacts/groups/models.py`
- `API/src/app/core/contacts/groups/service.py`
- `API/src/app/core/contacts/groups/router.py` + `schemas.py`

### Modified (1)
- `API/src/app/main.py` — wire router

**File budget:** ~6 files.

---

## Plan

1. Migration with RLS.
2. Static vs dynamic — single table, discriminator column. Dynamic stores filter; static stores explicit ids.
3. `preview_audience_size` reuses the existing `/contacts` query builder (DRY with campaigns audience filter in 3.5.9).

---

## Pre-implementation question

**Q:** Static vs dynamic — UX simplification. Sirf **dynamic** rakhein (filter-based, always recomputed), ya **both** support karen?

- **(a) Dynamic only.** Simpler model, no `contact_group_members` table needed. Every "group" is a saved filter. New contact joining your "Bangalore VIPs" filter auto-joins the group at send time.
- **(b) Both.** Static groups support "I uploaded this specific 47-contact list, those exact contacts no matter what" — important for one-off campaign blasts where you don't want auto-inclusion.

**Recommendation: (b)** — XLSX import (3.5.10) is going to want static groups ("contacts from sales_leads_q3.xlsx"). Both modes add ~20% code but cover real use cases.

---

## Verification + Self-check + Stop & report — standard
