# Step 4 — Lead → Contact + Deal conversion + row ergonomics (tel / WhatsApp / mailto, URL state, Lost-reason on update)

**Goal:** add the highest-impact funnel-handover feature (Lead → Contact + Deal) and round out leads' row-level UX (click-to-call / WhatsApp / mailto on cells, URL-state for filters, Lost-reason modal on status change). After this step, the leads page is the new pattern reference for the remaining update-* tracks.

**Depends on:** Step 3 + `update-contacts-page/` Step 4 (`PhoneLink`, `WhatsappLink`, `MailLink`, `UrlFilterStateDirective`).

## Files changed

### Modified backend
- `API/src/app/core/leads/router.py` — add `POST /leads/{id}/convert` returning the created/linked `{ contact_id, deal_id }`.
- `API/src/app/core/leads/service.py` — `convert_lead(...)` orchestrating contact + deal creation in one transaction.
- `API/src/app/core/leads/schemas.py` — `LeadConvertRequest`, `LeadConvertResponse`.

### New frontend
- `APP/src/app/features/user/core/leads/lead-convert-modal.component.ts`
- `APP/src/app/features/user/core/leads/lead-convert-modal.component.html`
- `APP/src/app/features/user/core/leads/lost-reason-modal.component.ts`
- `APP/src/app/features/user/core/leads/lost-reason-modal.component.html`

### Modified frontend
- `APP/src/app/features/user/core/leads/leads-api.service.ts` — `convert(id, payload)`.
- `APP/src/app/features/user/core/leads/leads.page.ts` — URL state wiring + status-change handler dispatches Lost-reason modal when needed.
- `APP/src/app/features/user/core/leads/leads.page.html` — apply phone/email/wa directives; mount UrlFilterState; mount Convert + Lost-reason modals.
- `APP/src/app/features/user/core/leads/lead-card.component.html` — apply phone/email link directives.
- `APP/src/app/features/user/core/leads/lead-form-modal.component.ts/html` — when status set to Lost in the edit modal, surface required reason inline.

### Tests
- `API/tests/core/leads/test_convert.py` (new)

## Backend — `POST /leads/{id}/convert`

Body:
```json
{
  "pipeline_id": "<uuid>",
  "stage_id": "<uuid> | null",
  "contact_link_mode": "create" | "link" | "auto",
  "linked_contact_id": "<uuid> | null"
}
```

`contact_link_mode`:
- `"create"` — always mint a new contact from the lead fields (full_name, phone, email).
- `"link"` — link to an existing contact by `linked_contact_id` (validated tenant-scoped).
- `"auto"` (default) — search by E.164 phone suffix and case-insensitive email; if exactly one match, link; if none, create; if multiple, return `409` asking the FE to ask user to disambiguate.

`stage_id` defaults to the first stage of the pipeline (queried server-side).

Service does (all in one async transaction):
1. Resolve / create `contact`.
2. Insert a `deal` in `pipelines/deals` table at chosen stage, owner = lead's owner, custom_data from the lead's `custom_data`.
3. Set `lead.status = "won"`, `lead.linked_deal_id = <new deal id>`, `lead.linked_contact_id = <contact id>`.
4. Write audit activity `type='convert'` on the lead with `body={"contact_id":..., "deal_id":...}`.
5. Activity hook bumps `last_activity_at` on lead + contact.

Permission required: `leads.write` AND `contacts.write` AND `pipelines.write`.

Response:
```json
{ "lead_id": "...", "contact_id": "...", "deal_id": "..." }
```

If the lead is not in `qualified` status → 422 "Only qualified leads can be converted." Reuses the state-machine rule from Step 1.

## Frontend — `lead-convert-modal.component`

Inputs: `lead` (the source `Lead`), `pipelines` (list from `PipelinesApiService`).

Body:
- Section 1: **Contact** — radio choices Create new / Link existing / Auto-match. If "Link existing," shows a contact-picker (typeahead via `GET /contacts?q=`).
- Section 2: **Deal** — pipeline dropdown, stage dropdown (depends on pipeline), title (defaults to lead title), value (defaults to lead value if any).
- Cancel / Convert buttons.

On confirm → `api.convert(leadId, payload)` → success snackbar "Lead converted; deal created in <pipeline>" with a "View deal" link to the pipeline.

## Frontend — `lost-reason-modal.component`

Inputs: `currentLostReason`, `currentLostReasonOther`.

Body:
- Required radio picklist: Price · Timing · Competitor · No-response · Other.
- If "Other" picked, required free-text field.
- Cancel / Save.

Output: `confirm` (emits `{ lost_reason, lost_reason_other }`), `cancel`.

Triggered from any UI that sets status to Lost: the form modal in `lead-form-modal.component`, the row-level "Mark Lost" button, the bulk-status modal.

## `leads.page.ts` — URL state

Reuses `UrlFilterStateDirective`:
```typescript
readonly urlState: UrlFilterStateConfig = {
  q: { signal: this.q, queryKey: 'q' },
  source: { signal: this.sourceFilter, queryKey: 'source' },
  status: { signal: this.statusFilter, queryKey: 'status' },
  assigned_to_id: { signal: this.assigneeSignal, queryKey: 'assignee' },
  scope: { signal: this.scope, queryKey: 'scope' },
  sort: { signal: this.sortKey, queryKey: 'sort' },
  order: { signal: this.sortOrder, queryKey: 'order' },
  no_activity: { signal: this.noActivityFilter, queryKey: 'no_activity' },
  page: { signal: this.page, queryKey: 'page' },
  view: { signal: this.view, queryKey: 'view' },  // pipeline | list
};
```

## Row ergonomics

- Apply `[appPhoneLink]` / `[appWhatsappLink]` / `[appMailLink]` to phone + email cells in list view.
- In `lead-card.component.html`, same — phone + email inside the card become clickable.
- Replace `window.confirm` in `onDelete` paths with shared `ConfirmDialog`.

## Test `test_convert.py`

1. Convert with `contact_link_mode="create"` → new contact + new deal + lead.status="won".
2. Convert with `contact_link_mode="link"` cross-tenant → 422.
3. Convert with `contact_link_mode="auto"` and unique phone match → links existing contact.
4. Convert with `auto` and multiple matches → 409 with candidate ids.
5. Convert when lead is in `new` (not `qualified`) → 422.
6. Convert is atomic — simulate a `deal` insert failure → contact insert rolled back.

## Acceptance

1. Qualified lead detail or list shows **Convert** button.
2. Convert modal lets user choose Create / Link / Auto and pick pipeline + stage. Submit → lead becomes Won; contact + deal exist; activity logged.
3. Marking a lead Lost (anywhere) prompts the Lost-reason modal; missing reason blocks save.
4. List cells: phone is `tel:`; WhatsApp icon opens `wa.me`; email is `mailto:`.
5. URL `/user/leads?status=qualified&assignee=me&sort=last_activity_at&order=desc&view=list&page=2` round-trips cleanly.
6. Bulk delete shows styled `ConfirmDialog`.
7. Smoke test on Ajay's Workspace.

## Lucide icons used

`arrow-right-circle` (convert), `alert-triangle` (lost reason warning), `download` (if CSV is later added). All standard.

## Self-check vs the 10 rules

- ✅ Rule 1 — convert calls `core/pipelines` + `core/contacts`, all Layer 1.
- ✅ Rule 2 — atomic transaction; tenant-scoped.
- ✅ Rule 10 — convert ships atomic, lost-reason gated everywhere.

## Stop-and-report template

> ✅ Step 4 complete. Leads track done.
> **Files changed:** 13 (3 modified backend, 4 new FE components, 5 modified FE files, 1 new test).
> **What you can verify:**
> 1. Convert flow: qualified lead → Contact + Deal in one transaction; audit on lead + bump on contact.
> 2. Lost-reason modal triggered on every Lost path (single + bulk + form modal).
> 3. tel/wa/mail links on list + card.
> 4. URL state round-trips for all filters + view + page.
> 5. Auto-match dedup behaviour (single hit links; multi-hit returns 409).
> **Tests added:** `test_convert.py` (6).
> **Self-check:** all 10 rules ✅.
> **Leads track complete.** Recommend proceeding to `update-walkins-page/`.
