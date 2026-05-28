# Step 3.5.11 — Contact import frontend: 3-step wizard

**Goal:** UI for the import backend (3.5.10) — 3-step wizard at `/user/contacts/import`. Upload → map columns → dry-run preview → commit.

**Phase:** 3.5
**Depends on:** 3.5.10
**Status:** PROPOSED — awaiting "begin"

After this step the operator can: drag XLSX onto upload zone → see auto-detected column mapping with overrides → see dry-run summary "192 will be added, 8 errors (phone dupes)" → click Commit → toast "192 contacts added, group 'Q3 Leads' created".

---

## Scope

### In-scope

- New route `/user/contacts/import` linked from Contacts page header ("Import contacts" button).
- 3-step wizard component using a step indicator:
  - **Step 1 — Upload:** Drag-drop zone, accepts `.xlsx` / `.csv`. Submit → POST `/upload` → moves to step 2.
  - **Step 2 — Map columns:** Shows detected column names, each with a dropdown to map to a contact field (full_name, phone, email, owner_id, source, tag, custom.*). Auto-fills suggested mapping. Toggle "Create a group from this import" → group name input.
  - **Step 3 — Preview & commit:** Shows summary (X will be added, Y errors, Z dupes), error table (collapsible), Commit button. On commit → toast + redirect to contacts list (filter pre-set to the new group if created).
- Service additions to `contacts-api.service.ts`: upload, dry-run, commit.

### Out-of-scope

- Import history page → P2.
- Resume an interrupted import → P2.

---

## Files to touch

### Created (~4)
- `APP/src/app/features/user/core/contacts/imports/import-wizard.page.{ts,html}`
- 3 step components if they get large, else inline `@if (step()===1)` blocks

### Modified (~3)
- Contacts routes
- Contacts page header — "Import" button
- Contacts API service — types

**File budget:** ~6-7 files.

---

## Plan

1. Wizard component holds the `import_id` + step state across the flow.
2. File upload via `FormData` + `HttpClient` with progress observable.
3. Column mapping uses dropdowns built from a backend-provided field catalog (reuses `MappingTarget` shape from Phase 5).
4. Error rendering: virtualized list if >100 errors.

---

## Pre-implementation question

**Q:** Drag-drop zone par files drop ho jane ke turant baad upload start kar do ya **"Continue" button** chahiye?

- **(a) Auto-upload on drop** — faster, but no chance to cancel before parsing
- **(b) Drop → preview filename → "Continue" button to upload** — operator can swap file if wrong one dropped

**Recommendation: (b)** — drag-drops can be accidental, especially on touchpads. One extra click prevents wasted parses.

---

## Verification + Self-check + Stop & report — standard
