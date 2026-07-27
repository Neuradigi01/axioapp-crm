# Step 18 — Small pages sweep

**Goal:** Restyle the remaining smaller modules in one pass: calls, catalog, activities, tasks, walk-ins, custom-fields, standard-fields, pipelines (config side), AI, staff (portal side handled separately in Step 19-alt if needed), whatsapp (channel config), services.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## Scope

Each module gets:
- Page-header (Step 6 pattern).
- Table / card grid using the shared primitives.
- Any module-specific modal restyled with AIXO look.

Modules to touch (each folder under `APP/src/app/features/user/core/`):
- `calls/` — call log table + call detail drawer.
- `catalog/` — product / service catalog list + editor.
- `activities/` — activity timeline (already in Contacts drawer; standalone list here).
- `tasks/` — task list + task modal (reuses appointment modal pattern).
- `walk-ins/` — walk-in log list + capture modal.
- `custom-fields/` — field definition table + create / edit drawer.
- `standard-fields/` — field visibility table.
- `pipelines/` — pipeline config: stages list + drag-reorder.
- `ai/` — AI assistant page (chat pane layout, similar to conversations Step 11 chrome).
- `staff/` — staff list (admin side of staff-portal).
- `whatsapp/` — WhatsApp channel config (business account picker + templates listing embedded).
- `services/` — services catalog (if distinct from catalog).

## Approach

Because there are 12 modules to touch, do them in **2 batches of ~6** — each batch = one commit, ≤10 files. Batch cut is agent's call based on file count.

## Files to touch

Per module: 1–3 files typically. Total across all: ~24–36 files.

## Verification

- Every module page renders in dark + light with consistent look.
- No `bg-white`, `bg-zinc-*`, or `#hex` colors left behind in these modules.

## Out of scope

- Module-specific logic.
- Rewiring registries or navigation.
