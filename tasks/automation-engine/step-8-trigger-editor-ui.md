# Step 8 — Trigger editor UI

**Goal:** Create / edit page at `/user/automations/new` and `/user/automations/{id}`. Operator picks an event, builds conditions, picks a channel + template, sets delay + recipient resolver, saves. Reuses the channel chips + template picker from the Templates module.
**Status:** Pending
**Depends on:** Step 7 (list page wired), `tasks/template-library/` (template picker reused).

---

## Scope

In-scope:
- `APP/.../core/automations/editor/automation-editor.page.{ts,html}`:
  - Top bar: name input + enabled toggle + Save / Save & Test buttons.
  - Step-by-step form (single page, four cards stacked):
    1. **When this happens** — event picker (dropdown of events from `/event-types`), shows sample payload below.
    2. **Only if** — condition builder (visual chip-based rule builder; can leave empty for "always").
    3. **Then send** — channel dropdown + template picker. Template picker filters by chosen channel; only `internal_status=published` AND `external_status in (n_a, approved)` templates shown.
    4. **To** — recipient resolver dropdown (`contact.email | contact.phone | user.email | custom`); if `custom`, accepts a dot-path string.
  - Sidebar (right): "Sample payload" panel that lets the operator paste a JSON payload and click "Test conditions" to see whether the trigger would match.
- `APP/.../core/automations/editor/condition-builder.component.{ts,html}`:
  - Visual chip-style rule builder. Click "+ Add rule" → field path + operator + value. Multiple rules combine with AND by default; click "Switch to OR" toggles.
  - Field path autocomplete based on the chosen event's sample payload shape.
  - Operator dropdown: `=, ≠, in, not in, contains, starts with, >, ≥, <, ≤, exists, doesn't exist, regex`.
  - Value input adapts to operator (text, number, list, none).
- `APP/.../core/automations/editor/template-picker.component.{ts,html}`:
  - Modal that reuses the Templates API service to list + filter templates by channel + published. "Open editor in new tab" link for editing the template.
- `APP/.../core/automations/editor/event-info-card.component.{ts,html}`:
  - Shows the event-type label + description + sample payload (collapsed JSON viewer).
- Save & Test button: POSTs to a new endpoint `POST /api/v1/automations/triggers/{id}/dry-run {payload}` that runs the dispatcher path against the supplied payload **without** writing a run row or sending a real message — returns "would match: true/false", "would send to: <recipient>", "rendered preview".
- `API/src/app/core/automation/router.py` extended with the `dry-run` endpoint.
- Route added: `/user/automations/new` and `/user/automations/:id`.
- Jest smoke for editor + condition builder.

Out of scope:
- Run history (Step 9).
- Manual "Run now" (Step 9).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/automations/editor/automation-editor.page.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/automation-editor.page.html` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.html` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/template-picker.component.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/template-picker.component.html` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/event-info-card.component.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/editor/event-info-card.component.html` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — add editor routes |
| `API/src/app/core/automation/router.py` | edit — dry-run endpoint |

**~10 files. ~700 lines** — at Rule 8 upper bound; per-file ~60-80 lines.

## Plan

1. Backend dry-run endpoint first — small, reuses `service.match_triggers` + variable resolver without writing rows.
2. Event info card — pulls event catalog from `/event-types`.
3. Condition builder — most complex piece. Signal-driven chip list + form-array.
4. Template picker modal — re-uses `templates-api.service.ts` from Templates module.
5. Editor page composes the four cards.
6. Save flow: validates (name, event, channel + template, recipient) → POST or PATCH → toast → routes back to list.
7. Save & Test → calls dry-run → modal with result.
8. Jest: editor page loads with an existing trigger, condition builder add/remove, template picker open + select.

## DB changes / migrations

None.

## Tests

4 Jest cases:
- Editor loads an existing trigger correctly (populates name + event + conditions + channel + template).
- Adding a condition appends to the rule array; deleting removes.
- Template picker opens, filters by channel, selecting one closes + updates parent.
- Save & Test calls dry-run + shows the result.

Backend pytest:
- `test_dry_run_does_not_create_run_row`
- `test_dry_run_returns_match_decision`
- `test_dry_run_renders_template_with_payload`

## Smoke

```
1. /user/automations → click New automation.
2. Pick event: lead.created. Sample payload shows below.
3. Add condition: source = "website".
4. Channel: email. Template: pick "Lead Confirmation" from picker.
5. Recipient: contact.email.
6. Click Save & Test → modal: paste {"source": "website", "contact": {"email": "x@y.com"}} → result: "would match, would send to x@y.com, preview: ...".
7. Save → returns to list, new trigger visible + enabled.
8. Edit it → reload → all fields restored.
```

## Risks

- Condition builder UX complexity — visual rule builder is the hardest UI piece in this track. Keep it linear (chip list) at v1; defer drag-drop nested groups to a polish step.
- Sample payload shape varies per event — the catalog endpoint must provide accurate samples; if a new event is added without updating the catalog, the editor breaks for that event type. Pin test on the catalog vs publish-site shapes.

## Self-check (10 rules)

`features/user/core/automations/`. ✓ org_id via JWT. ✓ N/A custom fields. ✓ N/A dynamic forms (trigger editor is static; rule builder is part of the module). ✓ Sidebar already registered. Permissions gate save. ✓ pack.yaml untouched. ✓ 10 files / ~700 lines — at Rule 8 upper bound; justified by the editor being the operator's main surface. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 8 — Trigger editor UI
Files: 10
Verify: full editor flow create-edit-save + dry-run test + template picker integration.
Tests: 4 Jest + 3 pytest cases.
Awaiting "proceed".
```
