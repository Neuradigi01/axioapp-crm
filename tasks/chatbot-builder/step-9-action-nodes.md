# Step 9 — Action nodes: Condition + Delay + Add Tag + Set Custom Field + API Request

**Goal:** Ship the five non-messaging action nodes, including the SSRF-hardened HTTP client for API Request.
**Depends on:** Steps 6, 8
**Status:** Pending

## Scope

**In-scope**
- `nodes/condition.py` — if/else branching on a condition AST (reuses `core/workflows/conditions.py` evaluator).
- `nodes/delay.py` — park the run for a configured duration; resumed by `sweep_chatbot_waits`.
- `nodes/add_tag.py` — call existing `core/tags/service.py` (or `core/contacts/service.py:add_tag`) to add/remove a tag.
- `nodes/set_custom_field.py` — write a static or variable-interpolated value via `save_target_registry`.
- `nodes/api_request.py` — HTTP GET/POST/PUT/PATCH/DELETE with SSRF-guarded client, response capture via JSONPath, retries, timeout.
- `core/chatbots/http_client_safe.py` — the locked-down HTTP client (Decision §16).

**Out of scope**
- CRM extras (Handoff, Create Lead, etc) — Step 10.
- AI node placeholders — Step 10.

## Files to touch

- `API/src/app/core/chatbots/nodes/condition.py` (created)
- `API/src/app/core/chatbots/nodes/delay.py` (created)
- `API/src/app/core/chatbots/nodes/add_tag.py` (created)
- `API/src/app/core/chatbots/nodes/set_custom_field.py` (created)
- `API/src/app/core/chatbots/nodes/api_request.py` (created)
- `API/src/app/core/chatbots/http_client_safe.py` (created)

## Plan

1. `condition.py`:
   - Config: condition AST with operators `equals`, `not_equals`, `contains`, `starts_with`, `regex_matches`, `greater_than`, `less_than`, `is_set`, `is_empty`, boolean AND/OR/NOT.
   - Operands can reference `answers.*`, `contact.*`, `lead.*`, `variables.*`.
   - Reuse `core/workflows/conditions.py:evaluate` if it exists; else copy pattern.
   - Return `NodeResult(next_edge="true"|"false")`.
2. `delay.py`:
   - Config: `duration_seconds` (or `{amount, unit}`).
   - Park with `park_key=("delay", run_id, resume_at=now+duration)`.
   - `sweep_chatbot_waits` picks up rows where `resume_at <= now` and re-enqueues.
3. `add_tag.py`:
   - Config: `entity` (contact | lead), `tags: [<name>]`, `operation` (add | remove).
   - Call existing tag service; skip if already present (idempotent).
4. `set_custom_field.py`:
   - Config: `entity`, `field`, `value` (raw or `{{template}}`).
   - Resolve value via templates variable engine.
   - Call `save_target_registry.write` — same allow-list as Ask nodes (Case: exclude sensitive fields).
5. `api_request.py`:
   - Config: `method`, `url`, `headers`, `body` (JSON), `capture_path` (JSONPath), `save_capture_to` (variable name), `timeout` (max 30s), `retry_on_5xx` (max 3).
   - Call via `http_client_safe.request(...)`.
   - Store response fragment in `context.api[node_id]`; downstream nodes access via `{{api.<node_id>.<jsonpath>}}`.
   - On 4xx/5xx: take `error` port; else `success`.
6. `http_client_safe.py`:
   - Resolves DNS; validates all resolved IPs are public (rejects private/loopback/link-local/ULA; rejects IPv4 in `10/8`, `172.16/12`, `192.168/16`, `169.254/16`, `127/8`, and equivalent IPv6).
   - HTTPS only (reject http URLs at save-time).
   - Response body size cap 1 MB; connection + read timeout enforced.
   - Redirects followed manually with re-validation of each hop's IP + scheme.

## DB changes / migrations

None.

## Tests to add

Location: `API/tests/core/chatbots/test_nodes_actions.py`

- `test_condition_true_false_edges`
- `test_condition_references_answers_and_contact`
- `test_delay_parks_and_resumes` (T38)
- `test_add_tag_idempotent`
- `test_set_custom_field_writes_value` (T34)
- `test_set_custom_field_sensitive_target_rejected` (T34)
- `test_api_request_captures_response` (T37)
- `test_api_request_ssrf_blocks_link_local` (T36) — `http://169.254.169.254/...`
- `test_api_request_ssrf_blocks_private_range`
- `test_api_request_ssrf_blocks_redirect_to_private`
- `test_api_request_https_only`
- `test_api_request_response_size_cap`
- `test_api_request_timeout_enforced`
- `test_api_request_5xx_takes_error_port`

## Verification checklist

**Backend**
- [ ] Manual test: build a flow with `api_request` calling a public JSON API (e.g. `https://api.github.com/zen`); response captured; downstream node uses captured value.
- [ ] Manual test: same node targeting `http://169.254.169.254/latest/meta-data/` → error, no request sent.
- [ ] Delay of 60s parks and resumes correctly.

**Frontend** — N/A.

**Code review**
- [ ] `http_client_safe.py` is the ONLY HTTP client used by the API Request node. No direct `httpx.get(...)` calls elsewhere in node handlers.
- [ ] SSRF checks run BEFORE the request, not on response.
- [ ] `set_custom_field` cannot bypass the save-target allow-list — 422 at both save-time AND runtime.

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` scoped
- [ ] Sidebar/permissions N/A
- [ ] Reuse — reused conditions.py, save_target_registry, existing tag service
- [ ] Query efficiency — condition AST evaluated in-memory against `context`, no per-eval DB
- [ ] Zero TODOs

## Stop & report

Report the SSRF blocklist entries, an `api_request` sample request/response pair, and a delay-then-resume test-fire transcript. Await "proceed".
