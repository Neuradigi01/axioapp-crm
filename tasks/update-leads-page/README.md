# Update Leads page

A focused track to bring `/user/leads` (pipeline + list view) up to standard-CRM expectations.

**Steps 1–4** ship the worklist core: last-activity, sortable columns, status workflow with Lost reason, lead transfer (single + bulk), pipeline-card ownership badges, and Lead → Contact + Deal conversion. Reuses the shared primitives built in [update-contacts-page/](../update-contacts-page/).

**Steps 5–7** add the power-list features expected from any mature CRM: cursor pagination (scales past 500 leads), CSV export, a column-customization menu, a small JSON filter DSL with an advanced-filter modal, a rule-based `lead_score` column, and saved views (per-user + shareable). Establishes the **`saved_views` + filter DSL + cursor pagination + column prefs** pattern that the remaining `update-*-page` tracks (walk-ins, contacts v2, tasks) will reuse rather than reinvent.

## Why this exists

Leads is the most-trafficked page for sales reps. The existing page has pipeline + list views, source filter, import, and `assigned_to_id` already on the model — but the worklist features are incomplete:

- **No `last_activity_at`** — reps can't sort "who hasn't been touched in 7+ days," the single most-used CRM filter.
- **No sortable columns** in list view; no owner badge on pipeline cards.
- **No status workflow on the lead itself** — pipeline stage exists, but lead `status` (New / Contacted / Qualified / Won / Lost) is a separate dimension and is not surfaced.
- **No Lost reason** — when a deal is lost, no required dropdown captures why. Kills win-loss analytics.
- **No lead transfer UI** — column exists, but no pencil-icon reassign on the card and no bulk reassign on the list.
- **No Lead → Contact + Deal conversion** — qualified leads have to be re-entered manually. Standard CRM mints a contact + opens a deal in one click.
- **No phone-first ergonomics** — same gaps as contacts pre-update.
- **No URL state** for filters.

Leads is also where the `convert` workflow lives — single biggest funnel-handover feature in any CRM.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **`last_activity_at` denormalisation** | Same hook as `update-contacts-page/` Step 1; extend the dispatch dict in `activities/service.py` to include `lead`. |
| **Sortable list headers** | Created, Last activity, Status, Score (if present). |
| **Status workflow** | `status` column on `leads` (already exists per the model) surfaced as a column + filter. Required state-machine: New → Contacted → Qualified → Won / Lost. |
| **Lost reason** | Required dropdown when status set to Lost (Price / Timing / Competitor / No-response / Other). New `lost_reason` + `lost_reason_other` columns. |
| **Pipeline card upgrades** | Owner avatar + last-activity badge on every card. Click card → assignee popover with reassign action. |
| **Single + bulk transfer** | Reuses `ReassignModal` + `BulkActionBar`. New permission key `leads.reassign`. Audit-as-activity on every transfer. |
| **Lead → Contact + Deal conversion** | "Convert" button on qualified lead. Creates / links a contact, opens a deal in the chosen pipeline at stage 1. |
| **Row ergonomics** | tel / mailto / WhatsApp on phone / email; URL state for filters; styled confirm delete. |
| **Visibility scope** | "My / Team / All" assignee toggle on list + pipeline header. Permission-driven defaults. |

## What this track does NOT do (even after Step 7)

- Does not add **AI / predictive** lead scoring; the engine is rule-based (operator-defined points per condition).
- Does not add **inbox / unified messaging** thread on the lead; lives in `conversations` module.
- Does not change the existing **import** flow or the **dedup-on-ingest** path (already done in lead-infrastructure/).
- Does not add a Kanban board view for the list (pipeline view already serves that purpose).
- Does not change the bulk-import or webhook ingestion paths.
- Does not add **OR-group / nested-group** support in the advanced filter UI (backend DSL supports `any` siblings; UI v1 is `all`-only).
- Does not migrate column preferences from localStorage to backend (Step 6 uses localStorage; saved-views' `config.columns` covers the named-view case).

## Acceptance criteria

### After Steps 1–4 (worklist core)

A sales rep on `/user/leads`:

1. **List view** shows Owner, Status, Last activity columns. Headers sortable.
2. **Pipeline view** shows owner avatar + last-activity badge on each card.
3. **Status filter** chips: All · New · Contacted · Qualified · Won · Lost.
4. **Marking Lost** opens a required reason picker before save.
5. **Marking Won** requires a linked deal.
6. **Admin / Owner / Store Manager** can reassign single (pencil on card / detail) and bulk (list checkboxes → BulkActionBar).
7. **Reassign event** appears on lead timeline.
8. **Convert button** on Qualified lead → modal asks "Create contact named X? Open deal in <pipeline> at <stage>?" → on confirm, contact + deal created, lead linked.
9. **Phone / email cells** are click-to-call / mailto / WhatsApp.
10. **URL reflects filters**; refresh-safe.
11. **Junior Sales** sees no reassign / convert buttons; their default scope is "Mine."

### After Steps 5–7 (power list)

12. **Cursor pagination** — list renders with a "Showing X–Y of N" footer; Previous / Next walk a server-side cursor; page-size 25/50/100/200.
13. **Export CSV** button (gated on `leads.export`) downloads only the visible columns × active filter; ~10k rows in one file without browser freeze.
14. **Column customization** — show/hide/reorder columns via a small menu; persisted to localStorage per user.
15. **Score column** — colour-banded `lead_score` pill (cold/warm/hot/on-fire); sortable; populated by the rule engine.
16. **Advanced filter modal** — build `field op value` clauses (AND) over standard + custom fields; field-type-aware ops.
17. **Saved views** — name + save the current filter + sort + columns + scope. Optional "Share with team" toggle (read-only for non-owners).
18. **Settings → Lead Scoring** page — Owner/Admin create/edit/delete rules; "Recompute scores now" button.
19. **Junior Sales** sees no Export CSV button, no Settings → Lead Scoring tab, no rule-edit affordances; can still apply shared saved views.

## Steps

### Worklist core (Steps 1–4)

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | Backend: `last_activity_at` + sort/filter + Lost reason + status state-machine + `leads.reassign` | Pending | ~½ day |
| 2 | Frontend list: Owner, Status, Last activity columns + sortable + status filter + scope toggle | Pending | ~½ day |
| 3 | Pipeline cards: owner avatar + last-activity badge + click-to-reassign popover + bulk select on list | Pending | ~½ day |
| 4 | Lead → Contact + Deal conversion + row ergonomics (tel/mail/wa, URL state, styled delete) | Pending | ~1 day |

### Power list (Steps 5–7)

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 5 | Backend: cursor pagination + filter DSL + CSV export + `lead_score` column with rule engine | Pending | ~1 day |
| 6 | Frontend: pagination + column customization + CSV button + advanced filter builder | Pending | ~1 day |
| 7 | Saved views (backend + UI) + Lead scoring rules admin page | Pending | ~1 day |

**Total: ~5.5 working days.** Stop and report after each per Rule 9.

## Dependencies

- [update-contacts-page/](../update-contacts-page/) — REQUIRED. Provides `ReassignModal`, `BulkActionBar`, `ConfirmDialog`, `RelativeTimePipe`, `UsersDirectoryService`, `PhoneLink`/`WhatsappLink`/`MailLink`, `UrlFilterStateDirective`.
- Phase 2 leads module — Done.
- Phase 2 pipelines module — Done. Convert flow calls existing `POST /pipelines/{id}/deals`.
- Activities service hook from `update-contacts-page/` Step 1 — extended here to add `lead` to dispatch.
- RBAC role templates — `leads.reassign` added to `permissions/role_templates.py` for Owner + Admin templates.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 1 new migration (`0053_leads_last_activity_and_lost_reason.py`), 4 modified (`leads/models.py`, `schemas.py`, `service.py`, `router.py`), 1 modified (`activities/service.py` — extend dispatch). | Backfill `last_activity_at` in migration. |
| Step 2 frontend | 3 modified (`leads-api.service.ts`, `leads.page.ts/html`), 1 modified (`lead-card.component.html`). | |
| Step 3 frontend | 1 new (`lead-reassign-popover.component.ts/html`), 2 modified (`leads.page.ts/html` for selection state + BulkActionBar), 1 modified (`pipeline-board.component.html`). | |
| Step 4 frontend | 1 new (`lead-convert-modal.component.ts/html`), 1 new (`leads-api.service.convert(...)`), 2 modified (`lead-form-modal.component.ts/html` for Lost reason), 1 modified (`leads.page.html` for tel/wa/mail + URL state). | |
| Step 5 backend | 1 new migration (`0070_leads_pagination_score_and_scoring_rules.py`), 3 new (`leads/filter_dsl.py`, `csv_export.py`, `scoring.py`), 5 modified (`leads/models.py`, `schemas.py`, `service.py`, `router.py`, `module.py`). | At Rule 8 upper bound; split if overruns. |
| Step 6 frontend | 5 new (`column-customization-menu.component.ts`, `advanced-filter-modal.component.ts/html`, `shared/column-prefs.service.ts`, `shared/filter-dsl.types.ts`), 3 modified (`leads-api.service.ts`, `leads.page.ts/html`). | Pagination footer inlined; no new component. |
| Step 7 backend + frontend | 1 new migration (`0071_saved_views.py`), 5 new in `saved_views/` (`models.py`, `schemas.py`, `service.py`, `router.py`, `module.py`), 1 modified (`main.py`), 2 new FE (`saved-views-api.service.ts`, `settings/lead-scoring-rules.page.ts`), 3 modified FE (`leads.page.ts/html`, `user.routes.ts`). | Slightly over Rule 8 soft target; defensible because `saved_views/` is a single new module. |
| Tests | `tests/core/leads/test_last_activity.py`, `test_status_workflow.py`, `test_convert.py`, `test_pagination_and_csv.py`, `test_lead_scoring.py`, `tests/core/saved_views/test_saved_views.py`. | Smoke target Ajay's Workspace. |

**Total ~50 files across 7 steps.** Each step targets ≤10 files / ≤400 LOC; Steps 5 and 7 noted as at-or-just-over the soft target with a mid-stream split fallback per Rule 9.

## Invariants this track enforces

| Rule | Where |
|---|---|
| Lead status transitions validated server-side | `leads/service.update_status(...)` checks `(from, to) in ALLOWED_TRANSITIONS`. |
| Lost reason required when status=Lost | Schema validator: `if status == "lost" and not lost_reason: 422`. |
| Won requires a linked deal | Service-level check; rejected at API edge. |
| Reassign always writes an activity | Same pattern as `update-contacts-page/` Step 3. |
| Convert is atomic | Contact + Deal created in one DB transaction; lead linked or rollback. |
| Filter DSL accepts only whitelisted fields + ops | `leads/filter_dsl.parse` raises on unknown; ≤20 clauses; depth-1. |
| CSV export streams server-side | Never materializes the whole result set in memory; ~1000-row chunks. |
| Saved-view share toggle gates update/delete to owner only | `saved_views/service.update_view` checks `owner_user_id == caller_id`. |
| Lead score is computed server-side | Never trust a client-supplied `lead_score`; field excluded from `LeadCreate`/`LeadUpdate`. |
| Scoring rule edit triggers org-wide recompute | `service.create/update/delete_scoring_rule` enqueues `recompute_org_scores`. |

## Self-check against the 10 rules

- ✅ Rule 1 — `core/leads/` does not import from packs. Convert calls `core/pipelines` + `core/contacts`, all Layer 1.
- ✅ Rule 2 — `org_id` already on leads. New columns inherit tenancy.
- ✅ Rule 3 — `custom_data` untouched; `lost_reason` is a first-class field (analytics demand it).
- ✅ Rule 5 — sidebar registry untouched.
- ✅ Rule 6 — `leads.reassign` registered via module registry.
- ✅ Rule 7 — `pack.yaml` untouched.
- ✅ Rule 8 — 4 steps; largest ~10 files.
- ✅ Rule 9 — stop-and-report after each.
- ✅ Rule 10 — Lost reason ships with the workflow; convert ships atomic.

## After this track

- Pipeline + list views feel like Pipedrive / Zoho without the bloat.
- Lead → Deal conversion replaces manual re-entry.
- Leads list scales past 500 / 5 000 / 50 000 rows on the same indexes.
- Operators can express their qualification logic as scoring rules and see hot leads bubble to the top.
- Power users save and share named views — no more "rebuild that filter every morning."
- Pattern established for `update-walkins-page/` and `update-appointments-page/` (cursor pagination + filter DSL + column prefs + saved views are now generic reusables in `core/shared/` and `core/saved_views/`).
