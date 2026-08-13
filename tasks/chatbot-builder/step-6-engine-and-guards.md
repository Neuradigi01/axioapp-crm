# Step 6 — Engine + Celery step processor + meters + human-takeover cancel + WA 24h window

**Goal:** Land the runtime that walks bot graphs, parks runs at wait nodes, resumes on events, enforces reply caps + human-takeover cancel + WA 24h session window — before any send-capable node exists.
**Depends on:** Steps 1, 2, 5
**Status:** Pending

## Scope

**In-scope**
- `core/chatbots/engine.py` — `start_run`, `resume_run`, `process_step`, `park_run`, `cancel_run`, node-handler dispatch via registry, error handling, retry policy.
- `core/chatbots/tasks.py` — Celery tasks: `process_chatbot_step`, `sweep_chatbot_waits` (reuses `core/workflows/sweep_waits` primitive; documents the shared use).
- Per-conversation cap enforcement + per-org cap enforcement using `tbl_chatbot_meters` (Step 1); atomic increment SQL per Decision §9.
- Human-takeover cancel: hook into `conversations/service.py:send_outbound()` — if outbound is from a real user (not a bot run), find parked runs on that conversation and cancel with reason `human_took_over`.
- WA 24h session-window helper in `core/chatbots/channel_bridge.py` (helper only, no send code yet).
- Test-fire endpoint `POST /api/v1/chatbots/{id}/test-fire` — dry-run enforced (Case #22).

**Out of scope**
- Node handlers themselves — Steps 7-10.
- Actual WA/Email send methods — Step 7.

## Files to touch

- `API/src/app/core/chatbots/engine.py` (created)
- `API/src/app/core/chatbots/tasks.py` (created)
- `API/src/app/core/chatbots/channel_bridge.py` (created — window helper only)
- `API/src/app/core/chatbots/router.py` (modified — add `test-fire` endpoint)
- `API/src/app/core/chatbots/service.py` (modified — `test_fire_service` orchestration)
- `API/src/app/core/chatbots/data_access.py` (modified — meter helpers + cancel helpers)
- `API/src/app/core/conversations/service.py` (modified — human-takeover hook in `send_outbound`)

## Plan

1. `engine.py` — `start_run(bot, event, is_test=False)`:
   - Build initial context `{conversation_id, contact_id, lead_id, last_inbound_*}`.
   - Insert `ChatbotRun` row with `status='running'`, `is_test`.
   - Enqueue `process_chatbot_step.delay(run_id, first_node_id)`.
2. `process_step`:
   - Load run + node config from graph JSON.
   - Reject if run status is not `running` or `parked`.
   - Enforce meters BEFORE invoking any send-capable node: check per-conversation + per-org caps; on cap → cancel run with `skip_reason`.
   - Enforce WA session-window (via helper) for WA send-capable nodes; outside window → take `session_expired` port if defined, else cancel with reason `session_window_expired`.
   - Dispatch to node handler via registry: `NODE_REGISTRY[node.type](run, node, context)` → returns `NodeResult(next_edge, output, park_key=None, skip_reason=None)`.
   - Park handling: if `park_key` returned, mark run `parked`, insert wait row, done. Sweeper resumes.
   - Advance to next node via `next_edge` or default output edge.
   - Cap max-steps per run at 100 (Decision §10 for cycle guard).
3. `resume_run(run_id, resume_event)` — inbound message arrives, matcher decides to resume:
   - Load parked run, verify wait_key matches, feed the resume event into context (`last_inbound_text`, etc), re-enqueue `process_chatbot_step`.
4. Meters:
   - Increment via `UPDATE tbl_chatbot_meters SET count = count + 1 WHERE org_id=? AND bot_id=? AND conversation_id=? AND count < cap RETURNING count`.
   - Empty return = cap hit; take the appropriate cancel branch.
   - Per-org meter row has `bot_id=NULL, conversation_id=NULL`.
   - `window_start` refreshed lazily on next check when `now > window_start + 24h`.
5. Human-takeover:
   - In `conversations/service.py:send_outbound()`, after successful send, if the outbound message's `chatbot_run_id IS NULL` (i.e. it's a human-sent), query `SELECT id FROM tbl_chatbot_runs WHERE conversation_id = ? AND status = 'parked'`, and `cancel_run(id, reason='human_took_over')` on each.
6. WA session-window helper `is_within_wa_window(conversation_id) → bool` — checks the last INBOUND message timestamp against 24h. Used by all WA send-capable node handlers in Step 7.
7. `POST /chatbots/{id}/test-fire` — required body has `simulated_inbound_text`, `simulated_contact_id_or_placeholder`. Enforces `dry_run=true`; `is_test=true` on the run; all sends produce transcript entries; save-to writes to per-run scratch; timeouts compressed to 30s; test run auto-deleted after 24h.

## DB changes / migrations

None (schema was pre-provisioned in Step 1).

## Tests to add

Location: `API/tests/core/chatbots/test_engine.py`

- `test_start_run_creates_run_and_enqueues_first_step`
- `test_process_step_advances_via_next_edge` (mock node handler)
- `test_process_step_parks_on_park_key`
- `test_resume_run_from_parked` (T22)
- `test_meter_atomic_increment_no_lost_update`
- `test_per_conversation_cap_ends_run` (T30)
- `test_per_org_cap_ends_run_and_pauses_bots` (T31)
- `test_human_takeover_cancels_parked_runs` (T32)
- `test_max_steps_100_hard_cap`
- `test_test_fire_is_dry_run_by_default` (T50)
- `test_test_fire_writes_to_scratch_not_real_records` (T50)

## Verification checklist

**Backend**
- [ ] Engine can walk a stub 3-node graph end-to-end with fake handlers (no send).
- [ ] Meter table shows correct counts after simulated inbound bursts.
- [ ] Human-takeover manual test: park a run, send outbound from Inbox UI → run canceled.
- [ ] Test-fire returns transcript + diagnostics; no rows written to `tbl_contacts` / `tbl_leads`.

**Frontend** — N/A.

**Code review**
- [ ] Only `service.py` calls `db.commit/rollback/refresh/flush` — engine goes through service.
- [ ] Celery tasks handle exceptions and mark run `errored` rather than dying silently.
- [ ] `resume_run` idempotency: re-invoking with the same resume event doesn't advance twice.

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` present in every DB read/write
- [ ] Sidebar/permissions N/A
- [ ] Reuse — sweep_waits reused from core/workflows/
- [ ] Query efficiency — `list_parked_runs_for_conversation` uses composite index (org_id, conversation_id, status)
- [ ] Zero TODOs

## Stop & report

Report the engine's state-machine diagram (start → running → parked → resumed → completed / canceled / errored), the meter increment SQL statement, and a test-fire transcript sample. Await "proceed".
