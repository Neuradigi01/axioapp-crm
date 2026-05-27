# Update Contacts page

A focused track to bring the `/user/contacts` list + detail up to standard-CRM expectations: ownership, last-activity, sortable columns, reassign (single + bulk), row ergonomics (call / WhatsApp / mailto), URL-state, duplicate detection, CSV export. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready.

## Why this exists

The contacts page today is a clean v1 directory: search, source/tag filters, paginated table, create/edit modal, detail with tabs. It works, but it misses the worklist features a sales rep expects:

- **No `assigned_to_id` on the `contacts` table at all** — the only Layer-1 entity missing it (`leads`, `walk_ins`, `appointments`, `tasks` all have it). No "my contacts," no transfers, no workload reports possible.
- **No `last_activity_at`** — sales reps can't sort the list by "who hasn't been touched recently." Activities exist but aren't surfaced on the row.
- **No sortable columns** — only chronological order (server default).
- **No reassign UI** — even if the column existed, there's no way to change the owner.
- **No click-to-call / WhatsApp** — Indian furniture sales is phone-first; copying digits out of a cell is friction.
- **Filters are local-only** — source/tag dropdowns derive from the *currently loaded page*, not master lists. Filters change between pages.
- **No URL state** — refresh, share, browser-back all lose filter state.
- **Delete uses `window.confirm`** — bypass of the styled confirm modal used elsewhere.

Contacts is also the *foundation page* for this whole upgrade track: it's where the shared primitives (`ReassignModal`, `BulkActionBar`, `RelativeTimePipe`, `UsersDirectoryService`, `PhoneLink` / `WhatsAppLink` / `MailLink`) get built once and then re-used by Leads, Walk-ins, Appointments, Tasks.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **Owner column + filter** | Avatar + name on each row. Filter dropdown: All / Me / Unassigned / `<user>`. |
| **Last activity column + sort** | Relative-time ("2h ago", "3d ago"). Default sort: `last_activity_at desc`. |
| **Sortable headers** | Name, Created, Last activity. Click to toggle asc/desc. |
| **Reassign (single)** | Pencil icon on contact-detail Owner field → opens `ReassignModal`. Admin / Owner / Store Manager only (gated). |
| **Reassign (bulk)** | Row checkboxes on list → floating `BulkActionBar` → "Reassign to…" picker. Same permission gate. |
| **Audit on transfer** | Every reassign auto-logs an activity entry: *"Priya reassigned this contact from Rahul to Anita."* |
| **Click-to-call / mailto / WhatsApp** | Phone / email cells become `tel:` / `mailto:` / `https://wa.me/<digits>` links via shared directives. |
| **Duplicate warning on create** | Existing GIN indexes on phone + email — modal checks before save and surfaces "A contact with this phone exists: [view]". |
| **URL-state for filters + page** | `q`, `source`, `tag`, `assigned_to_id`, `sort`, `order`, `page` all round-trip to query params. |
| **CSV export** | Header button → exports current filter (server-side endpoint). |
| **Page-size toggle** | 25 / 50 / 100. |
| **Styled confirm delete** | Replace `window.confirm` with the shared `ConfirmDialog`. |

## What this does NOT do

- **No lifecycle-stage field** on contact. Funnel position is the pipelines module's job; adding a second status field would duplicate.
- **No saved views / segments.** Defer until reps ask.
- **No inline editing on detail.** Modal works fine.
- **No consent flags / phone normalisation** — those move to `update-leads-page/` Step 4 (where the same primitive serves contact + lead).
- **No engagement / lead score, watchers, @-mentions, keyboard shortcuts, avatar color-hash, custom column picker.** Out of scope.

## Acceptance criteria

After this track, a sales rep opening `/user/contacts`:

1. **Sees a Owner column** populated for any contact assigned to a user (Unassigned otherwise).
2. **Sees a Last Activity column** showing relative time, or "—" if nothing logged.
3. **Can click column headers** to sort by Name / Created / Last activity (toggle asc/desc).
4. **Can filter by assignee** — dropdown defaults to "All"; selecting "Me" filters to caller's contacts.
5. **Can click phone** → device dial / softphone opens; **click WhatsApp icon** → opens `wa.me/<phone>`; **click email** → `mailto:`.
6. **Can multi-select rows** (admin / owner / store-manager only) and **bulk reassign**, **bulk delete**, or **bulk add tag** via floating action bar.
7. **Can reassign a single contact** from the detail-page Owner field (pencil icon) — permission-gated.
8. **Sees a duplicate warning** when creating a contact whose phone or email already exists.
9. **URL reflects filters** — refresh or share preserves state.
10. **Can export current filter** as CSV via a header button.
11. **Filter dropdowns are stable** between pages (source from master, tags from `GET /contacts/tags`).
12. **Reassign event appears in the timeline** as an activity ("X reassigned from Y to Z").

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: assignee + last_activity columns, migration, sort/filter, activity hook](step-1-backend-assignee-last-activity.md) | Pending | ~½ day |
| 2 | [Frontend: Owner + Last Activity columns, sortable headers, assignee filter](step-2-frontend-owner-last-activity-columns.md) | Pending | ~½ day |
| 3 | [Reassign UI (single + bulk) + shared `ReassignModal` + `BulkActionBar`](step-3-reassign-ui-shared-primitives.md) | Pending | ~1 day |
| 4 | [Row ergonomics: click-to-call / mailto / WhatsApp + URL-sync + duplicate warning + CSV export](step-4-row-ergonomics.md) | Pending | ~1 day |

**Total: ~3 working days.** Stop and report after each per Rule 9.

## Dependencies

- Phase 2 contacts module — Done.
- Phase 2 activities module — Done. The activity-insert hook on `service.py` adds the `last_activity_at` bump for `entity_type == "contact"`.
- `GET /users` endpoint — Done. Reused for the Owner dropdown.
- RBAC permission keys — `contacts.read`, `contacts.write` exist. **New key** `contacts.reassign` is added in Step 3, registered in the contacts module registry.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 1 new migration (`0052_contacts_assignee_and_last_activity.py`), 3 modified (`models.py`, `schemas.py`, `service.py`, `router.py`), 1 modified (`activities/service.py` for the bump hook). | Backfill `last_activity_at` in the migration. |
| Step 2 frontend | 3 modified (`contacts-api.service.ts`, `contacts-list.page.ts/html`), 1 modified (`contact-detail.page.html`), 1–2 new shared (`shared/relative-time.pipe.ts`, `shared/users-directory.service.ts`). | Tailwind only. |
| Step 3 frontend | 2 new shared (`shared/reassign-modal.component.ts/html`, `shared/bulk-action-bar.component.ts/html`), 2 modified (`contacts-list.page.ts/html`), 1 modified (`contact-detail.page.html`). 1 modified backend (`contacts/router.py` adds `POST /contacts/{id}/reassign` + `POST /contacts/bulk-reassign`), 1 modified (`contacts/module.py` to register `contacts.reassign`). | Reassign emits an audit activity through the existing `activities/service.create_note(...)`-style pattern. |
| Step 4 frontend | 3 new shared (`shared/phone-link.directive.ts`, `shared/whatsapp-link.directive.ts`, `shared/url-filter-state.directive.ts`), 2 modified (`contact-form-modal.component.ts/html` for dup check), 2 modified (`contacts-list.page.ts/html` for CSV + page-size + URL state). 1 modified backend (`contacts/router.py` adds `GET /contacts/export.csv`). | Dup check reuses existing GIN indexes via a new `GET /contacts/check-duplicate?phone=…&email=…` endpoint. |
| Tests | curl/PowerShell smoke is the gate; minimal pytest for the new reassign endpoints + activity-bump hook. | Smoke target: Ajay's Workspace (`41f9ede9-…`). |

**Total ~24 files across 4 steps.** Each step ≤10 files / ≤400 LOC per Rule 8.

## Invariants this track enforces

| Rule | Where |
|---|---|
| Contacts remain tenant-scoped | `TenantScoped` ORM filter unchanged; all new endpoints gated by `require_permissions(...)`. |
| Reassign is permission-gated | `contacts.reassign` key required; junior sales role does not get it by default. |
| Audit log for every transfer | Every reassign call writes an activity to `activities` with `entity_type='contact'`, type='reassign'. |
| `last_activity_at` cannot be set client-side | Schema excludes it from `ContactCreate` / `ContactUpdate`. Only the activity-insert hook + migration backfill touch it. |
| No new card abstraction | List rows render directly from `ContactListItem`; no generic renderer added. Sort whitelist enforced server-side. |
| Pack rules untouched | `core/contacts/` adds no pack imports. Furniture-specific tags / sources stay in `pack.yaml`. |

## Self-check against the 10 rules

- ✅ Rule 1: `core/contacts/` does not import from `packs/`.
- ✅ Rule 2: `org_id` already on `contacts`; new columns don't change tenancy. RLS unaffected.
- ✅ Rule 3: `custom_data` JSONB untouched; `assigned_to_id` + `last_activity_at` are first-class columns, not custom fields.
- ✅ Rule 4: Form fields still rendered via `GET /custom-fields/contact/render`. New first-class fields render through the existing static dl, not the dynamic form.
- ✅ Rule 5: Sidebar entry unchanged; this track upgrades the destination.
- ✅ Rule 6: One new permission key (`contacts.reassign`) added via the existing module-registry pattern in [contacts/module.py](../../API/src/app/core/contacts/module.py).
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 4 steps; largest is ~10 files. Each step ≤30-min review.
- ✅ Rule 9: Stop-and-report after each step.
- ✅ Rule 10: No TODOs; reassign endpoint ships with audit, permission gate, and tenant filter on day one.

## After this track

- Contacts page is the new pattern reference for every other list page in the CRM.
- All shared primitives (`ReassignModal`, `BulkActionBar`, `RelativeTimePipe`, `UsersDirectoryService`, `PhoneLink`/`WhatsAppLink`/`MailLink`, `UrlFilterStateDirective`, `ConfirmDialog`) live in `core/shared/` and are ready to plug into [update-leads-page/](../update-leads-page/), [update-walkins-page/](../update-walkins-page/), [update-appointments-page/](../update-appointments-page/), [update-tasks-page/](../update-tasks-page/), [update-staff-offboarding/](../update-staff-offboarding/).
