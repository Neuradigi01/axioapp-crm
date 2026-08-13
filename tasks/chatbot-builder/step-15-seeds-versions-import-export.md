# Step 15 — Seed default bots + version history/rollback + import/export JSON

**Goal:** Close the track by seeding three default bots per org, shipping version history + rollback UI, and enabling JSON export/import for bot portability.
**Depends on:** Steps 1-14
**Status:** Pending

## Scope

**In-scope**
- `core/chatbots/seeds.py` — three default bot definitions:
  1. **Welcome Bot** — trigger keywords `hey / hello / hi / start`; sends welcome Text Button with 3 buttons (Browse products / See pricing / Talk to sales); routes accordingly.
  2. **Lead Qualification Bot** — trigger keywords `pricing / quote / demo`; asks 3 questions (name, email, use case) → creates lead → hands off to sales.
  3. **FAQ Router Bot** — trigger keyword `help`; sends List with 5 common questions; each row goes to a Template send with the answer + "Ask something else" link.
- All three seeded as `status='draft'` on org creation (per rule that new orgs don't auto-fire messages).
- Wire seed call into `core/tenants/service.py:create_organization` (or wherever the existing 15 default workflows are seeded per memory `project_workflows_absorb_automation.md`).
- Version history:
  - Every `save_chatbot` already appends to `tbl_chatbot_versions` (Step 2).
  - New endpoint `GET /chatbots/:id/versions` (already in Step 3 router).
  - New endpoint `POST /chatbots/:id/versions/:version_id/rollback` (already in Step 3).
  - Frontend `version-history-drawer` component — opens from builder top bar; lists versions with timestamp + user + diff summary; "Preview" and "Rollback" buttons.
- Import/Export JSON:
  - Export: `GET /chatbots/:id/export` returns portable JSON (excludes org-scoped IDs; keeps names/keys).
  - Import: `POST /chatbots/import` accepts JSON; creates a new bot in the requester's org with new IDs, preserving graph structure. Custom-field references remapped: if target field exists in the import-target org, use it; else create with matching name (with operator confirmation UI).
  - Frontend dialogs on the list page.

**Out of scope**
- Marketplace / template gallery — future.

## Files to touch

- `API/src/app/core/chatbots/seeds.py` (created)
- `API/src/app/core/tenants/service.py` (modified — call `seed_default_chatbots(org_id)` on org create)
- `API/src/app/core/chatbots/router.py` (modified — add `/export` and `/import` endpoints)
- `API/src/app/core/chatbots/service.py` (modified — export/import orchestration + custom-field remap)
- `APP/src/app/features/user/core/chatbots/builder/version-history/version-history-drawer.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/list/import-dialog.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/list/chatbots-list.component.html` (modified — wire the Import button)

## Plan

1. `seeds.py` — three fully-defined bot graphs in Python literals (each ~60-120 lines of JSON-shape config). Reuse the existing 15-default-workflows seeding pattern from memory.
2. Hook into `create_organization` — after the workflows seed call, `seed_default_chatbots(org_id, session)`. Idempotent (checks if already seeded).
3. Version history drawer:
   - Renders list of versions with author + date + change summary (nodes added/removed/modified counts).
   - "Preview" opens a read-only canvas overlay.
   - "Rollback" opens confirm dialog → calls rollback endpoint → reloads canvas.
4. Export format — versioned JSON envelope:
   ```json
   {
     "chatbot_export_version": 1,
     "exported_at": "...",
     "source_org": "<name only>",
     "bot": {
       "name": "...",
       "description": "...",
       "trigger_config": {...},
       "graph": {...},
       "referenced_standard_fields": [...],
       "referenced_custom_fields": [...],
       "referenced_templates": [...]
     }
   }
   ```
5. Import — preview screen shows: fields mapping (matched vs new-to-create), template references (matched vs missing), conflicts. Operator confirms → create.

## DB changes / migrations

`tbl_chatbot_versions` (id, org_id, chatbot_id, version_number, graph JSONB, saved_by, saved_at, change_summary) — if not created in Step 2, add here in migration `0191_chatbot_versions_table`.

## Tests to add

Location: `API/tests/core/chatbots/test_seeds_versions_import.py`

- `test_three_default_bots_seeded_on_org_create` (T51)
- `test_seeds_are_draft_status`
- `test_seeds_idempotent` — running twice does not duplicate.
- `test_version_history_appended_on_save` (T53 dup — already tested in Step 2, verify integration)
- `test_rollback_restores_prior_graph` (T53)
- `test_export_json_shape`
- `test_import_creates_bot_with_new_ids` (T52)
- `test_import_remaps_custom_fields_by_name`
- `test_import_missing_template_flags_conflict`
- `test_graph_semantically_round_trips_via_export_import` (T48 for portability)

## Verification checklist

**Backend**
- [ ] `run.cmd upgrade` applies any leftover migration (0191).
- [ ] Create a fresh org via existing admin flow → 3 seeded bots visible in `/user/chatbots` as `draft`.
- [ ] Save a bot 3 times → version history shows 3 entries + rollback works.
- [ ] Export bot → import into a different org → resulting bot has semantically identical graph.

**Frontend**
- [ ] Version history drawer opens, shows entries, rollback works with confirm dialog.
- [ ] Import dialog previews field mapping + template conflicts.
- [ ] Empty state on list page shows "Clone from a template" pointing to the seeded bots.

**Code review**
- [ ] Seed data is Python literals, no runtime-computed IDs (portable, deterministic).
- [ ] Import correctly rejects malformed JSON with 422.
- [ ] Export excludes sensitive fields (no org UUIDs, no user emails, no HMAC keys).

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` in every DB read/write
- [ ] Sidebar/permissions correct
- [ ] Reuse — reused the existing workflows seed pattern, existing template + custom-field services
- [ ] Under 10 files, under 400 lines
- [ ] Zero TODOs

## Stop & report

Report:
- The raw INSERT SQL for the 3 seeded bots (for pasting into the DB directly on existing orgs — see memory `feedback_execute_migrations_inline.md`).
- A screenshot of the list page for a fresh org showing the 3 seeded drafts.
- A screenshot of the version history drawer after several saves.
- A round-trip test (export from org A, import to org B, diff = 0).

Await "proceed" — this is the last step; on approval, the track closes.
