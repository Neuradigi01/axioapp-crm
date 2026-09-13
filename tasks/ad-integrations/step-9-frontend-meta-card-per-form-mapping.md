# Step 9 — Frontend: Meta card per-form Attach + Edit-Mapping (parity with Google card)

**Goal:** Bring the Meta card's per-form UX to parity with the Google card. Today Meta users can subscribe a Page but there is no UI to (a) create a per-form `tbl_integration_subscriptions` row or (b) edit its `field_mapping` JSON. The mapping editor modal and backend endpoints already exist (Google uses them); this step wires the Meta card into the same flow and adds one small backend extension so the mapping editor knows the actual question names of each Meta form.
**Track:** Ad Integrations
**Status:** COMPLETED
**Depends on:** Step 4 (Meta OAuth), Step 5 (Meta webhook + worker), Step 8 (field-mapping editor component + `PUT /subscriptions/{id}` endpoint).

---

## Scope

In-scope:

- **Backend — extend `GET /api/v1/integrations/meta/pages/{page_id}/forms` response** to include each form's question field names, so the mapping editor has a left-hand column to render. Meta forms can contain arbitrary custom questions (e.g. `what_service_are_you_interested_in`) — unlike Google's fixed vocabulary, the question keys are per-form, so we must fetch them from Meta's Graph API.
  - Extend `list_lead_forms_for_page` in `meta/subscriptions.py` to request the `questions{key}` field expansion.
  - Response now returns `{ form_id, name, status, questions: string[] }`.

- **Frontend service — extend `MetaLeadForm` interface** with `questions: string[]`.

- **Frontend `meta-card.component.ts`** — mirror the Google card's per-form controls:
  - Add `editMapping` output emitter (same event shape as Google).
  - Add `subscriptionsByForm` computed lookup (form_id → subscription row).
  - Add `toggleSubscribe(form)` action — creates or deletes the per-form `tbl_integration_subscriptions` row (calls the existing `POST/DELETE /integrations/subscriptions` endpoints Google already uses).
  - Add `openMapping(form)` handler that emits `editMapping` with the form's `questions` list.

- **Frontend `meta-card.component.html`** — for each form under an expanded Page, render two buttons:
  - **Attach / Detach** — creates or removes the per-form subscription row.
  - **Edit Mapping** — only visible when a subscription row exists.

- **Frontend `integrations-page.component.html`** — wire `(editMapping)="openMappingEditor(...)"` on `<app-meta-card>` (same handler the Google card already uses).

Out of scope:

- Per-form pipeline/owner routing (would require a schema change on `tbl_integration_subscriptions`; follow-up task).
- Auto-attach every discovered form on Page subscribe — **REVISED in Step 13:** industry-standard behaviour is now that subscribing a Page auto-attaches every form with heuristic defaults so leads flow immediately. The per-form Attach button on this card stays for forms Meta adds to the Page later.
- Multi-value / conditional-question handling (worker takes `values[0]` today; separator-join for multi-value follow-up).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/integrations/meta/subscriptions.py` | modified — fetch `questions{key}` in `list_lead_forms_for_page`; add `questions: tuple[str, ...]` to `MetaLeadForm` dataclass |
| `api/src/app/core/integrations/meta/router.py` | modified — surface `questions` list in `list_lead_forms_endpoint` response |
| `app/src/app/features/user/core/settings/integrations/integrations-api.service.ts` | modified — extend `MetaLeadForm` interface with `questions: string[]` |
| `app/src/app/features/user/core/settings/integrations/meta-card.component.ts` | modified — add `editMapping` output, `subscriptionsByForm` computed, `toggleSubscribe`, `openMapping`, `toggleInFlightFor` signal |
| `app/src/app/features/user/core/settings/integrations/meta-card.component.html` | modified — per-form Attach/Detach + Edit Mapping buttons |
| `app/src/app/features/user/core/settings/integrations/integrations-page.component.html` | modified — wire `(editMapping)` on `<app-meta-card>` |
| `api/tests/test_meta_oauth.py` | modified — extend `test_list_lead_forms_uses_page_token` to assert `questions` extraction + `questions{key}` field param; add `test_list_lead_forms_survives_malformed_questions` for the half-shaped-entries edge case |

Zero new files; strictly extensions to existing surfaces.

## Verification

Manual browser walk-through (Ajay's Workspace `41f9ede9-41b3-44ce-b489-3004566d4068`):

1. Settings → Integrations → open Meta card → connect if not already.
2. Load Pages → expand one → verify each form now shows two new buttons.
3. Click **Attach** on a form → confirm a `tbl_integration_subscriptions` row appears (via network tab / DB), button flips to **Detach** + **Edit Mapping** becomes visible.
4. Click **Edit Mapping** → modal opens with the form's actual question names in the left column (not a hardcoded list).
5. Save a mapping → verify it persists in `tbl_integration_subscriptions.field_mapping` JSONB.
6. Click **Detach** → confirm the row is deleted and buttons revert.

Backend verification: `GET /api/v1/integrations/meta/pages/{page_id}/forms` response includes `questions: [...]` per form.

## Self-check

- ✅ 10 rules: no `/core → /packs` import; every table already had `org_id`/`tbl_` prefix; custom-field flow untouched; forms still render dynamically from definitions; sidebar/permissions registry unchanged; pack manifest N/A; step < 400 LOC and ≤ 10 files; no TODOs/placeholders.
- ✅ Router → Service → DAL: backend edits touch only `router.py` + `subscriptions.py` (helper module, existing DAL exception documented — this step doesn't add SQL). No transactions moved outside `service.py`.
- ✅ Query efficiency: single Graph API call per form list (Meta's `fields=questions{key}` field expansion — same round-trip, no N+1).
- ✅ Reuse: leverages the existing `POST/DELETE /integrations/subscriptions` endpoints, the existing `FieldMappingEditorComponent`, the parent page's existing `mappingEditor` signal. No new endpoints, no duplicate components.
