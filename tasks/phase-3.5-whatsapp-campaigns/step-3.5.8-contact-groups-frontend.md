# Step 3.5.8 — Contact groups: list, create, edit page

**Goal:** UI for the groups backend (3.5.7) under `/user/contacts/groups`. Owner / Sales Manager can list, create (dynamic or static), edit, delete groups.

**Phase:** 3.5
**Depends on:** 3.5.7
**Status:** PROPOSED — awaiting "begin"

After this step a user can save the filter "source = walk-in AND tag = sofa" as a group named "Walk-in sofa shoppers", reusable across multiple campaigns.

---

## Scope

### In-scope

- Route `/user/contacts/groups` — list page with table (Name, Type [Dynamic/Static], Member count, Created by, Created at, Actions).
- Route `/user/contacts/groups/new` — create form with two modes:
  - **Dynamic:** form mirrors the existing `/contacts` filter UI (q, source, tag, owner, status).
  - **Static:** "Pick contacts" — searchable multi-select with chips. Member count visible.
- Route `/user/contacts/groups/:id/edit` — same form, prefilled.
- Sidebar: add "Groups" sub-item under "Contacts" (registered via existing module registry).
- API service additions to existing `contacts-api.service.ts`:
  - `listGroups()`, `createGroup()`, `updateGroup()`, `deleteGroup()`, `getGroup(id)`, `previewSize()`
- Delete confirmation modal — explicit because campaigns may reference the group.

### Out-of-scope

- Audience builder integration in Campaign Create → 3.5.9.
- Bulk member edit UX (CSV upload into a static group) → 3.5.11 covers it.

---

## Files to touch

### Created (~5)
- `APP/src/app/features/user/core/contacts/groups/groups-list.page.{ts,html}`
- `APP/src/app/features/user/core/contacts/groups/group-edit.page.{ts,html}` (used for create + edit)
- `APP/src/app/features/user/core/contacts/groups/groups-api.service.ts`

### Modified (~3)
- `APP/src/app/features/user/core/contacts/contacts.routes.ts` (or equivalent) — add 3 routes
- Sidebar/menu config — add "Groups" link
- Contacts API service — minor type re-exports

**File budget:** ~8 files.

---

## Plan

1. List page: standalone signals component, similar pattern to existing contacts page.
2. Edit page: typed reactive form, dynamic/static toggle disables fields.
3. Live member-count preview: debounced API call to `preview-size` while filter editing.

---

## Pre-implementation question

**Q:** Groups UX inside campaign modal — list ALL groups (dynamic + static), or **only "approved-for-WA"** groups (those whose contacts mostly have valid phone numbers)?

- **(a) All groups, no filter.** Operator may pick a group with 80 contacts where only 30 have phones — 50 messages fail.
- **(b) Filter to "phone-coverage ≥ 80%" by default.** Toggle to "Show all". Safer for new operators.

**Recommendation: (a)** with a **per-group phone coverage badge** ("47 of 80 contacts have phone") shown inline. Operator decides. No hidden filter — surprise UI hides problems.

---

## Verification + Self-check + Stop & report — standard
