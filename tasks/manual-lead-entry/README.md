# Manual Lead Entry

A small side track that makes manual in-app lead creation a **first-class ingestion channel** alongside the three richer channels that follow (bulk import, embeddable widget, ad webhooks). Establishes the `lead.source` taxonomy and the audit-log shape that every later channel reuses.

## Why this exists

The existing [`lead-form-modal.component.html`](../../APP/src/app/features/user/core/leads/lead-form-modal.component.html) lets a sales rep create a lead from inside the app — but that record carries no provenance. There is no way to tell, from the leads table, whether a row was typed by a rep, imported from a competitor's CSV export, submitted on the customer's website via the embeddable widget, or pushed in from a Google/Meta ad campaign.

For reporting, attribution, and dedup to work across the four upcoming ingestion channels, every lead row needs a stable `source` value from day one. The manual-entry channel is the simplest of the four and the right place to land that taxonomy + the per-channel audit-event pattern, with the smallest possible blast radius.

| Gap | What's missing today |
|---|---|
| **No `source` column on `leads`** | A row created via `POST /leads` carries no provenance. Reporting cannot answer "how many leads came from manual entry vs. our website widget last month?" |
| **No audit event on lead create** | Lead create is invisible to the audit log surface delivered in Phase 1.7. Every other domain action emits one; lead create silently doesn't. |
| **No "quick add" surface** | The only path to create a lead is to navigate to `/user/leads` and click "New". A rep on a call needs a global + button that opens the modal from anywhere in the app. |
| **Source attribution UX** | The modal does not show or let the user override the source. For manual entries this is fine (always `manual`), but the form is the canonical UI to confirm the value going into the DB. |

## What this does NOT do

- **Does not introduce a unified ingestion service.** Each channel keeps its own create path; they all just stamp `source` consistently and emit the same audit event. A shared `LeadIngestionService` is **not** built here; if cross-channel dedup grows beyond a row-level uniqueness check, it lands as a separate task during the ad-integrations track.
- **Does not implement deduplication.** Manual entry has no realistic dup risk (the user is looking at the screen and would see the existing lead in autocomplete). Dedup lands in the bulk-import + ad-integrations tracks where it matters.
- **Does not change the existing `POST /leads` contract** beyond adding a defaulted, optional `source` field. Existing callers keep working unchanged.
- **Does not touch `features/admin/`.** Per CLAUDE.md.

## Acceptance criteria

1. The `leads` table has a `source` enum column with values `manual | bulk_import | widget | google_ads | meta_ads`, defaulted to `manual`, NOT NULL.
2. Every `POST /leads` write emits an `lead.created` audit event including the `source` value and the actor's user id.
3. The existing lead form modal still works end-to-end with no behaviour change — the `source` is defaulted to `manual` server-side; the modal does not surface a source picker.
4. A floating "+" button in the app shell opens the lead-create modal from any `/user/...` page (permission-gated to anyone with `leads.create`).
5. On the leads list page, each row shows a small source badge (`Manual`, `Bulk import`, `Widget`, `Google Ads`, `Meta Ads`) so reps can see at a glance where each lead came from.
6. All of the above survives a fresh DB migration up + down + up cycle.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: `lead.source` enum column + audit event](step-1-backend-source-and-audit.md) | Pending | ~½ day |
| 2 | [Frontend: quick-add floating button + source badge on list](step-2-frontend-quick-add-and-badge.md) | Pending | ~½ day |

**Total: ~1 working day.** Each step verifiable in under 30 min per Rule 8; stop-and-report per Rule 9.

## Dependencies

- Phase 1.7 (audit logs) — Step 1 emits `lead.created`.
- Phase 2.11 / 2.12 (Leads backend + frontend) — existing surface that this track decorates.
- Phase 1.10 (app shell sidebar + header) — Step 2's floating button slots into the shell.
- Phase 1.5 (permissions) — Step 2's button respects `leads.create`.

## File budget

| Area | Files |
|---|---|
| Backend Step 1 | 1 migration + 3 modified (`leads/models.py`, `leads/schemas.py`, `leads/service.py`) + 1 modified (`audit/events.py` to declare the event key) + 1 test (`tests/test_leads_source.py`) |
| Frontend Step 2 | 2 new (floating-button component .ts + .html) + 2 modified (app shell layout + `leads.page.html` for badge) + 1 modified (`leads-api.service.ts` if response shape needs widening) |

**Total ~10 files across 2 steps.** Well under rule-8 ceilings.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| `lead.source` is the single source of truth for provenance | All four upcoming ingestion channels (bulk-import, widget, google_ads, meta_ads) write to this column — no parallel `imported_via` / `created_through` fields ever introduced. |
| `source` is NOT NULL and constrained to a fixed enum | DB-level. New values require a migration; channels cannot smuggle in free-text values. |
| Audit event shape is reusable | `lead.created` event carries `lead_id`, `source`, `actor_user_id`, `org_id`. Every later channel emits the same event with `actor_user_id = NULL` for system-created leads (widget submissions, webhook pushes). |
| `org_id` on every row | Already enforced on `leads`; no change. |
| `core/` never imports `packs/` | This track is core-only. No pack touched. |

## Self-check against the 10 rules

- Rule 1: Core-only; no pack import.
- Rule 2: `org_id` already present on `leads`; new `source` column is org-agnostic but every row already carries `org_id` + RLS.
- Rule 3: Not applicable — `source` is a canonical column, not a custom field.
- Rule 4: Existing lead form continues to render dynamically; the new column is server-defaulted, no form change needed in Step 1.
- Rule 5: Step 2's floating button registers via the existing app-shell pattern; no compile-time furniture coupling.
- Rule 6: Step 2 reads the existing `leads.create` permission key; no new key.
- Rule 7: `pack.yaml` unaffected. (Furniture pack may later choose to map specific ad sources to specific lead-source labels, but that's a separate concern.)
- Rule 8: 10 files across 2 steps, each verifiable in under 30 minutes.
- Rule 9: Stop-and-report after each step.
- Rule 10: No TODOs; the floating button is fully shipped (not behind a feature flag).

## After this track

- Every lead row carries provenance. Reporting can group by source.
- The audit log gains a `lead.created` event the dashboard can show.
- The bulk-import track (next) writes rows with `source='bulk_import'` and reuses the same audit event.
- The widget track writes rows with `source='widget'` and `actor_user_id=NULL`.
- The ad-integrations track writes rows with `source='google_ads' | 'meta_ads'`.
