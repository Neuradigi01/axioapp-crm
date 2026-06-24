# Step 2 — Trigger service and condition evaluator

**Goal:** Service-layer CRUD for `AutomationTrigger` + a condition evaluator that decides whether a given event payload matches a trigger's `conditions` JSONB + a recipient resolver that produces a concrete address (email / phone) from the payload.
**Status:** Pending
**Depends on:** Step 1 (schema + bus).

---

## Scope

In-scope:
- `core/automation/service.py`:
  - `create_trigger(org_id, payload, user_id) → AutomationTrigger`.
  - `update_trigger(org_id, id, payload, user_id)`.
  - `enable_trigger(org_id, id) / disable_trigger(org_id, id)`.
  - `delete_trigger(org_id, id)`.
  - `list_triggers(org_id, *, event_type?, enabled?, channel?, limit, offset)`.
  - `match_triggers(org_id, event_type, payload) → list[AutomationTrigger]` — returns enabled triggers whose `conditions` evaluate true against the payload.
- `core/automation/conditions.py`:
  - Condition shape: JSONB tree of `{field, op, value}` leaves with `AND`/`OR` branches. Supported ops: `eq, ne, in, not_in, contains, starts_with, gt, gte, lt, lte, exists, not_exists, regex`.
  - Field paths: dot-paths into payload (`contact.source`, `lead.estimated_value`, `contact.custom_data.lead_score`).
  - `evaluate(condition, payload) → bool` — pure function, no I/O.
  - Safe defaults: empty `{}` evaluates true; malformed condition logs and evaluates false (fail-closed).
- `core/automation/recipients.py`:
  - `resolve_recipient(trigger, payload, db) → str` — picks the address per `recipient_resolver`:
    - `contact.email` → payload's contact's email.
    - `contact.phone` → payload's contact's phone (E.164).
    - `user.email` → payload's user's email (used for system-events like `user.signed_up`).
    - `custom` → reads `recipient_resolver_config.path` and uses dot-path lookup into payload.
  - Returns `None` if the path can't resolve (caller skips and logs a "no_recipient" run row).
- `core/automation/exceptions.py`:
  - `TriggerNotFound`, `DuplicateTriggerName`, `InvalidCondition`, `MissingTemplateForChannel`.
- Tests for service + conditions + recipients.

Out of scope:
- HTTP routes (Step 3).
- Dispatcher (Step 4).
- Domain event publishers (Steps 5 + 6 + …).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/service.py` | **NEW** |
| `API/src/app/core/automation/conditions.py` | **NEW** |
| `API/src/app/core/automation/recipients.py` | **NEW** |
| `API/src/app/core/automation/exceptions.py` | **NEW** |
| `API/tests/automation/test_service.py` | **NEW** |
| `API/tests/automation/test_conditions.py` | **NEW** |
| `API/tests/automation/test_recipients.py` | **NEW** |

**~7 files. ~550 lines.**

## Plan

1. Conditions: pure-function evaluator. Tight test coverage for every operator + nested AND/OR.
2. Recipients: resolver registry keyed by string. Each resolver is a small function reading from the payload (no DB calls for `contact.*` if the payload includes the contact dict; otherwise a lookup).
3. Service: CRUD + match. Match runs `evaluate(condition, payload)` for every enabled trigger of the given event-type. Returns triggers in `id` ascending order so deterministic.
4. Channel/template consistency check on create + update: `template.channel == trigger.channel`. Reject with `MissingTemplateForChannel` otherwise.
5. Tests: CRUD happy path + duplicate-name rejection + RLS isolation + condition truth tables + recipient resolution for every resolver kind + empty/malformed conditions.

## DB changes / migrations

None — Step 1's tables already exist.

## Tests

15 pytest cases (heavy on conditions):
- `test_create_trigger_writes_row`
- `test_create_trigger_rejects_duplicate_name`
- `test_create_trigger_rejects_template_channel_mismatch`
- `test_enable_disable_idempotent`
- `test_match_triggers_returns_only_enabled`
- `test_match_triggers_returns_only_matching_conditions`
- `test_condition_eq_op`
- `test_condition_in_op`
- `test_condition_nested_and_or`
- `test_condition_empty_evaluates_true`
- `test_condition_malformed_evaluates_false_no_throw`
- `test_recipient_contact_email`
- `test_recipient_contact_phone`
- `test_recipient_user_email`
- `test_recipient_custom_dotpath`
- `test_recipient_resolves_to_none_when_missing`

## Smoke

```
1. uv run pytest API/tests/automation/ — green.
2. Python shell: create a trigger via service with conditions {"field": "lead.source", "op": "in", "value": ["website", "meta_ads"]}; match_triggers("lead.created", {"lead": {"source": "website"}}) returns it.
```

## Risks

- Dot-path lookups on arbitrary JSONB — must safely return None on missing keys without raising. Documented in `conditions.py`.
- Regex op needs a length cap on the pattern (`200` chars) + try/except to prevent ReDoS — mirror the Step-17 `keyword_engine.py` pattern from `whatsapp-platform-upgrade`.

## Self-check (10 rules)

`core/automation/`. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. N/A permissions (Step 3). pack.yaml untouched. ✓ 7 files / ~550 lines (tests-heavy). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 2 — Trigger service and condition evaluator
Files: 7
Verify: CRUD + match returns the right triggers for given event + payload; condition operators all work.
Tests: 16 pytest cases.
Awaiting "proceed".
```
