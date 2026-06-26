# Step 8 — Record actions (update fields, create task/note/quote/invoice)

**Goal:** Register the action handlers that modify CRM records — update a contact / lead field, set a custom field, create a task / note / appointment / quote / invoice / order. These are the second-most-used action category after Send.
**Status:** Pending
**Depends on:** Step 4 (engine + action contract). The origin modules' service layers (`core/contacts`, `core/leads`, `core/tasks`, `core/activities`, `core/appointments`, `core/quotes`, `core/invoices`) — workflows ALWAYS go through the other module's service, never its DAL, so business rules (validations, permission checks, audit logging) fire correctly.

---

## Scope

In-scope:

- `core/workflows/actions/records.py` registering these handlers:

  **Update actions** (modify existing record):
  - `record.update_contact_field` — node config: `{field_path: 'tags' | 'lead_score' | 'custom_data.preferred_channel', value: ..., contact_id_source: 'run.contact_id' | 'trigger_payload.<path>'}`. Calls `contacts.service.update_contact(...)`.
  - `record.update_lead_field` — similar for leads. Most common use: `status`, `score`, custom fields.
  - `record.update_lead_stage` — wrapper specifically for pipeline stage transitions. Triggers the pipeline-stage-changed event downstream.

  **Create actions** (insert new record):
  - `record.create_task` — node config: `{title: '<template-rendered string>', due_in_days: int, assignee_resolver: '<recipient kind>', priority: enum, related_to: 'contact' | 'lead' | 'quote' | 'invoice'}`. Calls `tasks.service.create_task(...)`.
  - `record.create_note` — adds a timeline note to the contact / lead.
  - `record.create_appointment` — scheduled at `now + delay_days` (or a fixed time in node config). Calls `appointments.service.create_appointment(...)`.
  - `record.create_quote` — body templated from the workflow context. Calls `quotes.service.create_quote(...)`. Operator pre-configures the quote line items in node config OR references a quote template (when `core/quote_templates/` ships — out of scope today, the handler accepts inline items).
  - `record.create_invoice` — same shape, calls `invoices.service.create_invoice(...)`.
  - `record.create_order` — for the order module when it ships (placeholder handler that raises `ActionNotImplemented` until then; registered so the validator accepts it in graphs).

- Variable resolution: every string-typed config field passes through the templates module's `resolve(...)` so operators can write `"Follow up with {{contact.first_name}}"` as a task title and have it render per-contact.

- Output: each handler's `ActionResult.output` carries the newly-created record's id + key fields so downstream nodes can branch on them. Example:
  ```python
  output = {'task_id': '...', 'task_due_date': '2026-07-15', 'task_assignee_id': '...'}
  ```
  These land in `step_run.payload` and become available to later nodes via `context.previous_step_outputs['<node_id>']`.

- Cross-module access discipline (per CLAUDE.md): every record handler imports the origin module's `service.py`, NEVER its `data_access.py`. So `update_contact` fires the contacts module's permission checks, custom-field validation, and audit emits — same as a real operator clicking Save in the UI.

- The handlers are wrapped in a per-action try/except that maps origin-module exceptions to clear skip_reasons:
  - `PermissionDenied` → `skip_reason='permission_denied'` (the workflow runs as the workflow's `created_by_user_id`; if that user no longer has the relevant write perm, the step skips).
  - `EntityNotFound` → `skip_reason='target_not_found'`.
  - `ValidationError` → `skip_reason='validation_failed'` + the validation message in `step_run.error`.

Out of scope:

- Conditional updates ("only update if current value is X") — operator achieves this with a branch node upstream.
- Bulk updates ("update every lead matching filter") — workflows are per-contact; bulk is a separate "batch operation" feature.
- The order module's create_order body (placeholder until order module ships).
- Webhook actions — Step 11 wires `record.call_webhook` as a flow-control action since it doesn't modify CRM state.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/actions/records.py` | **NEW** |
| `API/src/app/core/workflows/actions/__init__.py` | edit — side-effect import records.py |
| `API/src/app/core/workflows/exceptions.py` | edit — `ActionNotImplemented` for the order placeholder |
| `API/tests/workflows/test_record_actions.py` | **NEW** |

**~4 files. ~500 lines.**

## Plan

1. Records handler file with the eight handlers; each delegates to its origin module's service.
2. Exception types for permission / not-found / validation skip-reason mapping.
3. Action registry side-effect import.
4. Tests: each handler succeeds against a mocked origin service + handles each error category correctly.

## DB changes / migrations

None — workflows write through other modules' services which own their own schema.

## Tests

12 pytest cases:

- `record.update_contact_field` happy: contact updated, output carries new field value.
- `record.update_contact_field` permission denied: skip_reason='permission_denied'.
- `record.update_contact_field` validation failure: skip_reason='validation_failed' + error message.
- `record.update_lead_field` happy.
- `record.update_lead_stage` happy + downstream pipeline event fires (assert by spying on `bus.publish`).
- `record.create_task` happy: task row created with rendered title.
- `record.create_task` with template variables resolves correctly.
- `record.create_note` happy.
- `record.create_appointment` happy.
- `record.create_quote` happy with inline items.
- `record.create_invoice` happy.
- `record.create_order` raises `ActionNotImplemented` until the order module exists.

## Smoke

```
1. Workflow: trigger(lead.created) → record.update_lead_field(field='source_campaign', value='{{trigger_payload.source}}').
2. publish lead.created with payload {lead: {...}, source: 'AdWords-Diwali'}.
3. SELECT * FROM tbl_leads WHERE id=... → source_campaign='AdWords-Diwali'.
4. Add a second action: record.create_task(title='Call {{contact.first_name}} about {{lead.estimated_value}}', due_in_days=2, assignee_resolver='lead.owner').
5. Run completes → task row created in tbl_tasks with rendered title + owner.
```

## Risks

- "Workflow runs as the created_by_user" model means: when the workflow creator leaves the org, every workflow keeps firing as a phantom user. Mitigation: at user-deletion time, transfer ownership to the Owner role (the existing transfer-on-delete pattern for contacts/leads applies here too — a future step's responsibility).
- Cross-module service calls add ~10-50ms per action. Workflow with 10 record actions = 100-500ms per run step. Acceptable.
- Recursion: `record.update_lead_stage` fires `lead.stage_changed` event → another workflow triggered on that event → could update the same lead → infinite loop. Mitigation: Step 18 / 19 polish adds a per-run depth counter; workflows enrolled by an event already-firing in the same run's call stack are refused. Documented in `engine.py` and re-implemented properly in Step 19's diagnostics.

## Self-check (10 rules)

`core/workflows/actions/`. ✓ org_id-scoped via engine RLS context. ✓ Custom fields supported via `field_path: 'custom_data.<key>'`. ✓ N/A dynamic forms (the node-editor drawer's per-action config is static per action type). ✓ N/A sidebar. Permissions enforced through origin services. pack.yaml untouched. ✓ 4 files / ~500 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 8 — Record actions
Files: 4
Verify: 8 record-action handlers operational; cross-module service calls fire correctly; skip_reasons cover permission / not-found / validation.
Tests: 12 pytest cases.
Awaiting "proceed".
```
