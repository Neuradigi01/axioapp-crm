# Step 10 — CRM extras + Connect Flow + AI node placeholders

**Goal:** Ship the four CRM-specific node types (Handoff to Human, Create Lead, Book Appointment, Create Task), the `connect_flow` chain-to-another-bot node, and the two AI nodes as visible-but-inert placeholders.
**Depends on:** Steps 6, 8
**Status:** Pending

## Scope

**In-scope**
- `nodes/handoff_to_human.py` — assigns via existing `core/routing/` (round-robin / least-loaded / territory / specific-user); ends the current bot run.
- `nodes/create_lead.py` — creates a lead via `core/leads/service.py:create_lead`; dedup on phone/email as existing service handles.
- `nodes/book_appointment.py` — creates an appointment via `core/appointments/service.py:create_appointment`; conflict → `busy` port.
- `nodes/create_task.py` — creates a follow-up task via `core/tasks/service.py:create_task`.
- `nodes/connect_flow.py` — end current bot, start another bot in same org with `answers` and `context` passed through; runtime chain-depth guard (max 5).
- `nodes/single_ai_message.py`, `nodes/assign_ai_assistant.py` — inert placeholders that check `org.ai_provider_configured`; if not, take `error` port with a helpful log message; if `error` unconnected, fall through to a `handoff_to_human` if one exists nearby, else cancel run with `skip_reason='ai_not_configured'`.

**Out of scope**
- Real LLM integration for AI nodes — follow-up track.
- Chaining across orgs (Connect Flow requires same org).

## Files to touch

- `API/src/app/core/chatbots/nodes/handoff_to_human.py` (created)
- `API/src/app/core/chatbots/nodes/create_lead.py` (created)
- `API/src/app/core/chatbots/nodes/book_appointment.py` (created)
- `API/src/app/core/chatbots/nodes/create_task.py` (created)
- `API/src/app/core/chatbots/nodes/connect_flow.py` (created)
- `API/src/app/core/chatbots/nodes/single_ai_message.py` (created)
- `API/src/app/core/chatbots/nodes/assign_ai_assistant.py` (created)

## Plan

1. `handoff_to_human.py`:
   - Config: `assign_mode` (specific | round_robin | least_loaded | territory), `user_id` OR `team_id`, `final_bot_message` (optional).
   - Call existing routing helper; on success, send `final_bot_message` if set; cancel run with reason `handoff_completed` (not really cancelled — the run ended because the human took over).
2. `create_lead.py`:
   - Config: field map (`answers.name → lead.name`, etc), `source` label, `pipeline_id`, `stage_id`.
   - Uses answers + contact context to build the lead; passes through the existing dedup at `core/leads/service.py`.
   - On duplicate: take `duplicate` port; else `created`.
3. `book_appointment.py`:
   - Config: `title_template`, `duration_minutes`, `attendee_email_field`, `time_field` (which answer holds the requested time).
   - Calls `core/appointments/service.py`; conflict returned → `busy` port; success → `booked` port.
4. `create_task.py`:
   - Config: `title`, `assignee_mode` (bot_creator | round_robin | contact_owner), `due_in_hours` (default 24), `priority`.
5. `connect_flow.py`:
   - Config: `target_bot_id`.
   - Runtime chain-depth check: reads `context.chain_depth` (default 0), increments; if > 5, take `error` port.
   - Ends current run with reason `connect_flow_transferred`; starts target bot with same conversation_id + contact_id + carried `answers` + `chain_depth+1`.
6. AI stubs:
   - Both check `org.ai_provider_configured` (a boolean setting flag; false by default, seeded via a small migration `0189_org_ai_provider_configured`).
   - If false → log + take `error` port.
   - Node schema in `schemas.py` includes AI-specific config fields (system prompt, temperature, max tokens) so the follow-up track only needs to add the send logic, not schema changes.

## DB changes / migrations

`0189_org_ai_provider_configured` — add `ai_provider_configured BOOLEAN DEFAULT FALSE` on `tbl_organizations`.

## Tests to add

Location: `API/tests/core/chatbots/test_nodes_crm.py`

- `test_handoff_assigns_via_routing_and_ends_run` (T41)
- `test_create_lead_creates_lead_via_service` (T42)
- `test_create_lead_duplicate_takes_duplicate_port` (T42)
- `test_book_appointment_conflict_takes_busy_port` (T43)
- `test_create_task_creates_task_via_service` (T44)
- `test_connect_flow_ends_and_starts_target` (T39)
- `test_connect_flow_chain_depth_over_5_takes_error_port` (T40)
- `test_ai_message_no_provider_takes_error_port` (T45)
- `test_ai_assistant_no_provider_takes_error_port` (T45)

## Verification checklist

**Backend**
- [ ] Manual test-fire: full flow ending in Handoff correctly assigns and shows the assignee badge in Inbox.
- [ ] Manual test-fire: Create Lead persists a lead visible in `/user/leads`.
- [ ] Manual test-fire: Connect Flow chains from Bot A to Bot B with answers preserved.

**Frontend** — N/A.

**Code review**
- [ ] Every CRM-extra node goes through the target module's `service.py` — never bypasses to that module's DAL.
- [ ] `connect_flow` chain guard is enforced at runtime, not just save-time (guards against edited-across-multiple-bots cycles).

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` scoped
- [ ] Cross-module reads through the other module's service.py (not its DAL) — layered-architecture rule
- [ ] Zero TODOs

## Stop & report

Report a test-fire transcript for each of the four CRM-extra nodes and the connect-flow chain. Await "proceed".
