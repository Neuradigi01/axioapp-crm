# Leads — Update Status Flow

Manager (sir) supplied two reference screenshots from a competing CRM. This track ports the **operator workflow** those screenshots imply — a quick "Update Status" modal, a per-lead follow-up history, and a two-row filter toolbar on the Leads Center — onto our **existing** tasks + activities + move-stage plumbing. No new tables. No new columns. No new activity types.

> **Revised 2026-08-17** after Architect / Attacker / Absence reviewer gate. Prior draft invented `remarks` + `next_follow_up_at` columns on `tbl_leads` and a `follow_up` activity type — Architect CRITICAL: that would fork history away from `tbl_tasks` (with `TaskFollowupType`), which the dashboard's Today's Follow-ups widget already reads. Revised plan wires the modal to the existing tasks + activities modules so dashboard reports and modal writes stay in sync.

## Why this exists

Reps updating a lead today have two suboptimal options:

1. Open the full [`lead-form-modal`](../../APP/src/app/features/user/core/leads/lead-form-modal.component.html) — heavy; built for authoring, not for ticking a lead forward one call at a time.
2. Drag the kanban card — records the stage transition but has nowhere to write *why* ("customer wants a callback Tuesday 4pm").

Sir's reference solves both in one modal: contact-basics + stage + source + free-text remarks + next follow-up datetime, plus a per-lead history of every such touch.

Alongside that, the current [`leads.page.html`](../../APP/src/app/features/user/core/leads/leads.page.html) header exposes filters as chips + saved-views popover + advanced-filter modal. Sir wants a single visible two-row toolbar plus a `Search` button and `Export (CSV)` link.

## What already exists (this track just wires the modal to it)

| Concept | Existing shape | Cite |
|---|---|---|
| **Next follow-up on a lead** | `tbl_tasks` row with `related_entity_type='lead'`, `related_entity_id=<lead_id>`, `followup_type ∈ {call,whatsapp,email,document,meeting,other}`, `due_at`, `status ∈ {open,done,cancelled,missed}` | [`tasks/models.py:31-58`](../../API/src/app/core/tasks/models.py#L31) |
| **Follow-up dashboard buckets** | `today / pending / completed_today / overdue / missed` computed from `tbl_tasks` | [`dashboard/data_access.py:73-210`](../../API/src/app/core/dashboard/data_access.py#L73) |
| **Follow-up widget UI** | Reads & renders + reschedule + mark-missed from `tbl_tasks` | [`todays-followups.component.html`](../../APP/src/app/features/user/core/dashboard/widgets/todays-followups.component.html) |
| **"Remarks" text (what happened just now)** | `tbl_activities` row with `type='note'`, `payload={text}` | [`activities/schemas.py:34-42`](../../API/src/app/core/activities/schemas.py#L34) |
| **Stage change + status-sync + lifecycle stamps** | `move_stage_for_lead` in leads service — logs `status_change` activity, stamps `won_at`/`lost_at` | [`leads/service.py:927+`](../../API/src/app/core/leads/service.py#L927) |
| **Contact edits** | `contacts.update_service` — full contact patch | [`contacts/service.py:388`](../../API/src/app/core/contacts/service.py#L388) |
| **Task create / list / update / mark-missed** | `TasksApiService` on FE, `POST/GET/PATCH /tasks` on BE | [`tasks-api.service.ts`](../../APP/src/app/features/user/core/tasks/tasks-api.service.ts) · [`tasks/router.py`](../../API/src/app/core/tasks/router.py) |
| **Note create** | `activities-api.service.ts.createNote()` on FE, `POST /activities` (note-only) on BE | [`activities-api.service.ts:59`](../../APP/src/app/features/user/core/activities/activities-api.service.ts#L59) |
| **Leads list filtering** | `GET /leads` accepts `stage / status / source / assigned_to / q / sort / order / page / size / filter (DSL)` | [`leads/router.py:126-189`](../../API/src/app/core/leads/router.py#L126) |
| **CSV export** | `GET /leads/export.csv` with same filters, 50k cap | [`leads/router.py:233`](../../API/src/app/core/leads/router.py#L233) |

## What this does NOT do

- **Does not add `remarks` or `next_follow_up_at` columns to `tbl_leads`.** Follow-up = task row; remarks = note activity. The lead-detail panel derives "next follow-up" from a cheap `MIN(due_at)` over the lead's open tasks.
- **Does not add a `follow_up` value to `ActivityType`.** Would fork history away from `tbl_tasks`. The dashboard would silently ignore new-modal writes.
- **Does not replace [`lead-form-modal`](../../APP/src/app/features/user/core/leads/lead-form-modal.component.html).** Full editor stays for custom fields / contact dedup / won-lost capture. Update Status is a lightweight sibling.
- **Does not build a new `tbl_lead_follow_ups`.** Same reason as above.
- **Does not widen the modal into a full "Log Activity" surface** (call disposition + duration + outcome). That's how every mature CRM ships this button (HubSpot / Zoho / Pipedrive / Close, unsourced), but sir's ask is narrower. Flagged as a follow-up track.
- **Does not remove saved views or the advanced-filter modal.** Filter DSL stays; toolbar cells produce standard query params, advanced modal stays reachable as a secondary button.
- **Does not build a `.xlsx` writer.** Export button says "Export (CSV)" — labelled honestly. `.xlsx` is a separate track if sir asks.
- **Does not add a "Remarks" filter cell to the toolbar.** Post-replan, remarks live in `tbl_activities.type='note'` — filtering the leads list by "latest note contains X" needs a subquery per lead and is questionable UX. Reps use Data Search (matches contact) or open the lead and read the timeline. Reversible if sir insists.
- **Does not introduce optimistic locking beyond `if_current_stage`.** Two reps saving remarks on the same lead → both note rows survive with distinct authors + timestamps. Standard.
- **Does not touch `features/admin/` or `packs/furniture/`.**

## Decisions (locked — will not relitigate)

### D1. "Category Wise" = `pipeline_stage`. No new taxonomy.

Sir's reference labels the stage bucket "Category". HubSpot, Zoho, Pipedrive all treat pipeline stage as the primary lead bucket (unsourced — no `PRODUCT_BRIEF.md` yet). Our schema already has `pipeline_stage`. If sir later wants an orthogonal taxonomy (industry / segment / tier), it's a separate track with its own table.

### D2. Follow-ups are `tbl_tasks` rows. No new table. No new activity type.

Every "Update Profile" click that supplies a `next_follow_up_at` creates one `tbl_tasks` row via the existing `POST /tasks` service. The dashboard follow-ups widget picks it up unchanged. Per-lead history panel = `GET /tasks?related_entity_type=lead&related_entity_id=<id>&sort=due_at&order=desc`. Zero new SQL surface.

### D3. Remarks = `type='note'` activity. No new column, no denorm.

Every "Update Profile" click writes one `tbl_activities.type='note'` row via `POST /activities` with `payload.text = remarks`. The existing timeline already renders `note` rows. Prior draft's `lead.remarks` denorm column is dropped.

### D4. New endpoint `POST /leads/{id}/log-update` — truly atomic, single commit.

Payload:

```json
{
  "if_current_stage": "proposal",
  "contact_basics": { "full_name": "...", "phone": "...", "email": "..." } | null,
  "pipeline_stage": "qualified" | null,
  "source": "walk_in" | null,
  "remarks": "customer wants callback Tue 4pm",
  "next_follow_up": {
    "due_at": "2026-08-19T16:00:00Z",
    "followup_type": "call"
  } | null
}
```

Service opens **one session**, does in order:
1. Belt-and-braces `if lead.org_id != caller.org_id: 404` (Attacker HIGH #3).
2. If `if_current_stage` supplied and doesn't match DB → 409 (Absence #1 optimistic guard).
3. If `contact_basics` supplied → verify contact is linked to exactly **one** lead (Absence #2). If linked to >1, return 422 with message "Contact is on N leads — edit from contacts page." If OK, do a narrow patch (only `full_name/phone/email`) via a DAL helper — **not** `contacts.update_service` (Attacker HIGH #1: it accepts `assigned_to_id/custom_data/tags/source` too).
4. If `pipeline_stage` supplied and differs from DB (read fresh, ignore any client-supplied `from_stage`) → call `move_card` DAL directly + insert `status_change` activity via `activities.record_in_session` (which takes an external session and doesn't commit — [`activities/service.py:142`](../../API/src/app/core/activities/service.py#L142)) + stamp `won_at`/`lost_at` if entering won/lost stage (Absence #7 fabricated-history fix).
5. If `source` supplied → set on lead row.
6. Insert `note` activity via `activities.record_in_session` with `remarks` text.
7. If `next_follow_up` supplied → insert `tbl_tasks` row via a DAL insert (not via `tasks.service.create_task` which commits internally).
8. `session.commit()` **once**.

Service uses **only DAL calls + in-session activity helpers** — never reused services that commit internally (Attacker HIGH #2 + Architect MED). Refactoring `move_stage_for_lead` / `contacts.update_contact` to take an external session is out of scope; instead this endpoint inlines the atomic path.

Rate-limited with **weight=3** on the existing per-user leads-write bucket (Attacker MED #5 — endpoint does 3× the DB work of a plain PATCH).

### D5. Update Status button on lead-detail header, alongside Edit + Delete.

Sir's ask. Architect flagged the 3-button UX smell; deferred (see reject list).

### D6. Leads Center toolbar — two-row, sir's layout, wires to existing query params.

| Toolbar cell | Query param | Status |
|---|---|---|
| Date (from) | `created_from` | **new — add to router** |
| Between (to) | `created_to` | **new — add to router** |
| Order By/As | `sort` (widen to include `next_follow_up_due`) | widen |
| Category Wise | `stage` | existing |
| Source Wise | `source` | existing |
| Data Search | `q` | existing |
| User | `assigned_to` + `unassigned_only` (dropdown with a special "Unassigned" entry) | existing |
| Status | `status` (default `active`) | existing |
| Order Type | `order` | existing |
| Search button | submits | — |
| **Export (CSV)** — relabelled from sir's "Export In Excel" (Architect LOW: honest label) | `GET /leads/export.csv?<same params>` | existing |
| Header count `(filtered/total)` | Pagination `total` for filtered + one extra unfiltered count-only call for `total` | small add on service |

Saved-views + advanced-filter modal stay as secondary buttons to the right of row 2 — filter DSL is load-bearing for existing users.

### D7. `next_follow_up_due` sort — computed at query time.

Widen the leads `sort` enum with `next_follow_up_due`. Implementation: `LEFT JOIN LATERAL (SELECT MIN(due_at) FROM tbl_tasks WHERE related_entity_type='lead' AND related_entity_id=tbl_leads.id AND status='open') t ON true` and order by `t.min_due_at` with `NULLS LAST`. No new column; O(1) index on `tbl_tasks(related_entity_id, status, due_at)` (already exists — verify in step 2).

### D8. `next_follow_up.due_at` bounded to `now-1y ≤ v ≤ now+5y` (Attacker MED).

Prevents scheduler poisoning + year-9999 sort disruption. Sir's screenshot showed 1950 as an accidental placeholder default; UI defaults to *tomorrow 10:00 in the user's TZ* (Architect LOW). If a rep really wants a past date they'll see a validation error and can adjust the UI later.

### D9. CSV export escapes formula characters on every free-text column.

Attacker LOW: `remarks="=cmd|calc"` executes when a manager opens the CSV in Excel. Extend the existing exporter's Excel-safety prefix (already applied to phone at [`csv_export.py:257`](../../API/src/app/core/leads/csv_export.py#L257)) to every free-text column. Small cross-cutting fix; belongs here.

### D10. `contact_basics` uses a narrow schema, not `contacts.update_service`.

Attacker HIGH #1. New Pydantic schema `FollowUpContactBasics { full_name?, phone?, email? }`. Service copies those three fields into a fresh `Contact` DAL update. Also requires `contacts.write` in addition to `leads.write`.

## Cases

- **Two reps submit same lead simultaneously, different stages.** Optimistic `if_current_stage` guard: second submit 409s. Rep re-opens modal, sees the new stage. No fabricated `status_change` history.
- **Two reps write remarks concurrently.** Both `note` activity rows survive with distinct authors + timestamps. Timeline shows both. No denorm column to race on.
- **Shared contact across leads.** Contact edits blocked in the modal when contact.leads_count > 1 — reps redirected to contacts page. If sir prefers "allow but warn," reverse D4 step 3 and add a confirmation dialog.
- **`next_follow_up.due_at` set to the past.** Rejected by D8 bounds. Rep sees inline validation error and can adjust.
- **Rep clicks Update Profile 50 times/min.** Rate-limit weight=3 throttles at ~1/3 of the plain-PATCH ceiling. No new bucket.
- **Rep clicks Update Profile with no changes.** Still writes one `note` activity ("looked at this lead"). No task row. No stage move. No contact patch. Cheap.
- **Lead deleted while modal open.** Submit → 404. Modal shows error, closes. No orphaned rows.
- **Contact merged while modal open.** Existing contacts service returns survivor or 410. Modal shows error, closes.
- **What starts and never finishes:** nothing. One commit or one rollback.
- **What gets created and never re-claimed:** open tasks with past `due_at` become "overdue" — but the dashboard widget already renders + reschedules + mark-misses them. Cron auto-closes `overdue > 7 days` → `missed` per [`tasks/models.py`](../../API/src/app/core/tasks/models.py) comment. No new gravestone class.

## Tests — named, not counted

1. **atomicity** — `POST /leads/{id}/log-update` with stage + contact + note + task: on any downstream failure, transaction rollback removes all four.
2. **atomicity vs. reused services** — service never calls `move_stage_for_lead`, `contacts.update_contact`, or `tasks.service.create_task` (all of which commit internally); a grep-based pin-test asserts this.
3. **`if_current_stage` optimistic guard** — supplying a stale value → 409 with `current_stage` in the error payload.
4. **narrow contact patch** — payload with `contact_basics.assigned_to_id` returns 422 (extra field rejected).
5. **shared contact block** — contact linked to 2 leads + `contact_basics` in payload → 422 with actionable message.
6. **org isolation defence-in-depth** — caller in org A with `users.read` posting to lead in org B → 404.
7. **`from_stage` cannot be forged** — service reads from DB, ignores any client-supplied field; recorded `status_change` payload always uses server-derived `from`.
8. **`due_at` bounds** — `due_at < now-1y` or `> now+5y` → 422 with message.
9. **rate-limit weight** — 3-token deduction; abusive rep hits the ceiling in ~⅓ of the plain-PATCH request count.
10. **`contacts.write` gate** — caller with `leads.write` but no `contacts.write` and `contact_basics` in payload → 403.
11. **no-change post** — empty diff still writes one note; no task, no stage move.
12. **timeline preserves history** — both `note` and `status_change` activity rows appear in timeline for the lead after a mixed submit.
13. **follow-up panel on lead-detail** — shows open tasks (related_entity_type='lead') newest-due-first + mark-done button + reschedule button, reusing the dashboard widget's UI patterns.
14. **`GET /leads?created_from=X&created_to=Y`** — inclusive on both bounds; missing bound = unbounded.
15. **`GET /leads?sort=next_follow_up_due&order=asc`** — leads with the earliest open task first; leads with no open task appear last (`NULLS LAST`).
16. **Leads Center count** — header shows `(filtered/total)` where `total` is unfiltered org count.
17. **Export (CSV)** — button issues `GET /leads/export.csv` with the toolbar's current query params; every free-text cell is prefixed with `'` if it starts with `= + - @ \t \r`.
18. **Toolbar responsive** — 2-row grid collapses to single-column stack under 640px (Tailwind `sm:`).
19. **Modal validation** — invalid `due_at`, invalid stage key, > 2000-char remarks each show inline error before submit.
20. **Modal preload** — opens with lead's current stage/status/source pre-selected and the lead's next open task (if any) pre-populated in the follow-up datetime field.

## Steps

| # | Title | Status | Effort |
|---|---|---|---|
| 1 | [Backend: `POST /leads/{id}/log-update` atomic endpoint + narrow contact schema](step-1-backend-log-update-endpoint.md) | **COMPLETED** 2026-08-17 | ~45 min |
| 2 | [Backend: extend `GET /leads` with `created_from`/`created_to` + `sort=next_follow_up_due` + CSV cell escape + `(filtered/total)` count](step-2-backend-list-filters.md) | **COMPLETED** 2026-08-17 | ~30 min |
| 3 | [Frontend: `UpdateStatusModal` component + lead-detail header button + `logUpdate` FE API method](step-3-frontend-update-status-modal.md) | Pending | ~45 min |
| 4 | [Frontend: Follow-Up History panel on lead-detail page (reads `tbl_tasks` via existing `TasksApiService`)](step-4-frontend-follow-up-panel.md) | Pending | ~30 min |
| 5 | [Frontend: Leads Center two-row toolbar rebuild (wires to standard query params, keeps saved views + advanced-filter as secondary buttons)](step-5-frontend-leads-center-toolbar.md) | Pending | ~45 min |

**Total: ~3.25 hours across 5 steps.** Each step under 30 min to review per Rule 8; stop-and-report per Rule 9.

## Dependencies

- Tasks module (already exists — [`tasks/`](../../API/src/app/core/tasks/)) — modal writes via existing `TasksApiService.create()`.
- Activities module (already exists) — modal writes notes via existing `activities-api.service.ts.createNote()`.
- `activities.record_in_session()` (already exists — [`activities/service.py:142`](../../API/src/app/core/activities/service.py#L142)) — takes an external session and doesn't commit. Central to D4's atomicity.
- `move_card` DAL (already exists) — called directly to avoid `move_stage_for_lead`'s internal commit.
- `activity_entity_type` mapping (shipped earlier this session) — status_change rows go under `lead`.

## File budget

| Step | Files |
|---|---|
| 1 | 1 modified `leads/schemas.py` (add `LogUpdateRequest`, `FollowUpContactBasics`) + 1 modified `leads/service.py` (add `log_update_for_lead`) + 1 modified `leads/data_access.py` (helpers for direct DAL calls) + 1 modified `leads/router.py` (new endpoint) + 1 new test file. **5 files, ~350 LOC** |
| 2 | 1 modified `leads/router.py` + 1 modified `leads/service.py` (widen filters + sort + count) + 1 modified `leads/data_access.py` + 1 modified `leads/csv_export.py` (Excel-safety on remaining cols) + 1 new test file. **5 files, ~200 LOC** |
| 3 | 2 new (`update-status-modal.component.ts` + `.html`) + 1 modified `lead-detail.page.ts` + 1 modified `lead-detail.page.html` + 1 modified `leads-api.service.ts`. **5 files, ~400 LOC** |
| 4 | 2 new (`lead-follow-ups-panel.component.ts` + `.html`) + 1 modified `lead-detail.page.html`. **3 files, ~200 LOC** |
| 5 | 1 modified `leads.page.ts` + 1 modified `leads.page.html` + 1 modified `leads-api.service.ts`. **3 files, ~450 LOC** |

**Total ≈ 21 files across 5 steps.** Every step ≤ 5 files, ≤ 450 LOC — under Rule 8 ceilings.

## Self-check against the 10 rules

- **R1** — Core-only. No `/packs` import.
- **R2** — No new tables. All writes into existing `org_id`-scoped tables with RLS.
- **R3** — Not applicable (no custom-field surface added).
- **R4** — `UpdateStatusModal` renders known fields only; custom fields remain the full editor's job.
- **R5** — No sidebar / registry change.
- **R6** — Reuses `leads.write` + `contacts.write` + existing task permissions. No new keys.
- **R7** — No pack.
- **R8** — 5 steps, ≤ 5 files each, ≤ 450 LOC each. Each verifiable in under 30 min.
- **R9** — Stop-and-report after every step.
- **R10** — No TODOs, no feature flags, fully shipped.

## Deliberately rejected reviewer findings

- **Architect HIGH #2 — widen modal to "Log Activity" (call disposition / duration / outcome).** Sir's ask is narrower. Widening is a separate track — worth doing, not blocking this one.
- **Architect MED — 3 header buttons is a UX smell.** Sir explicitly asked for it. Revisit if reps complain.
- **Absence #8 — `get_lead_visible_to` conflates read/write.** Subsumed by D4 step 1's explicit org check.

## After this track

- Reps get sir's operator workflow: quick status update + follow-up history + Leads Center toolbar.
- Every operator touch is captured in existing tables (`tbl_activities`, `tbl_tasks`) — dashboard follow-ups widget stays truthful.
- Dashboard "Today's Follow-ups" widget shows tasks written by the new modal without any change.
- Reports (future track) can group leads by "has open follow-up / overdue / no follow-up scheduled" from `tbl_tasks` alone.
- The "Log Activity" widening (Architect HIGH #2) is the natural next track.
