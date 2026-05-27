# Update Staff offboarding

A focused track to close the "what happens to a leaving rep's records" gap. When an Admin deactivates a user in Settings → Staff, the system must:

1. Count their open records across all five entities (contacts / leads / walk-ins / appointments / tasks).
2. Block deactivation until a transfer target is chosen.
3. Bulk-reassign every open record to the target in a single atomic transaction.
4. Log a bulk reassign-audit activity on every transferred row.

Additionally, this track adds a small **Workload tab** in Settings → Staff: a simple table showing each user's open record counts. Same numbers used by the offboarding flow drive the optional workload mini-widget on the contacts / leads list pages (`update-contacts-page/` Step 4 stretch, `update-leads-page/` Step 2 stretch).

## Why this exists

A real CRM cannot lose track of a rep's records when they leave. Today:

- **Deactivating a user is a silent operation** — their `assigned_to_id` references stay, and their records become invisible to other reps (filtered out by "Mine" by default).
- **No bulk-transfer flow** for offboarding — Admin would have to manually reassign every record one by one.
- **No workload view** — Admin can't see how lopsided the assignments are.

The transfer mechanic itself (`ReassignModal` + `BulkActionBar` + bulk-reassign endpoints) is already built by the page-update tracks. This track just **orchestrates** them through the offboarding flow and adds the workload view.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **Pre-deactivation check** | New endpoint: `GET /users/{id}/open-records-counts` returns `{ contacts, leads, walk_ins, appointments, tasks }` open-record counts. |
| **Offboarding transfer modal** | Deactivate flow: count modal → "X has N1 contacts, N2 leads, …" → transfer target picker → confirm. |
| **Atomic bulk transfer** | New endpoint: `POST /users/{id}/transfer-records` body `{ "to_user_id": <uuid>, "entities": ["contacts", "leads", "walk_ins", "appointments", "tasks"] }`. Runs the per-entity bulk-reassign in a single transaction. Each row gets its audit activity. |
| **Workload tab** | New tab in Settings → Staff: table of users × open record counts. Permission-gated on `users.read` (Admin / Owner / Store Manager). |
| **Workload mini-widget (optional, consumer)** | Same numbers exposed via `GET /reports/workload` for the contacts / leads list page widgets. |

## What this does NOT do

- Does not **delete** the user record (deactivation is a soft state — `is_active=false`). The Owner has overall destroy power per `rbac-ownership/`.
- Does not change `core/auth` deactivation semantics — JWT sessions are already invalidated by `token_id` rotation on user update.
- Does not transfer **historical** rows (e.g. completed appointments, lost leads) — only open ones. Historical attribution stays with the original rep.
- Does not handle the Owner deactivation case — Owner cannot be deactivated; ownership transfer is a separate, already-existing flow (`rbac-ownership/` Step 3).
- Does not add notifications to the target / the leaving rep (depends on notifications module — can be added later in a notifications track).

## Acceptance criteria

An Admin in Settings → Staff:

1. Clicks **Deactivate** on user "Anita."
2. System shows a confirm modal: *"Anita has 12 contacts, 5 leads, 3 appointments, 4 tasks assigned. Transfer to:"* with a user-picker dropdown.
3. Picking a target + confirm → all 24 records bulk-reassigned to the target. Anita's `is_active` set to `false`. JWT sessions invalidated.
4. Anita's records each show a new timeline activity: *"Admin transferred this from Anita to Rahul during deactivation."*
5. Admin can open a new **Workload** tab in Settings → Staff → sees the per-user counts table.
6. Picking **Skip transfer** is **disabled** when open counts > 0. (Forced safety — no orphans.)
7. **Junior staff / non-Admin** does not see the Deactivate button (existing gate).
8. Owner cannot be the deactivation target (already enforced).

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | Backend: `GET /users/{id}/open-records-counts`, `POST /users/{id}/transfer-records`, atomic bulk-reassign | Pending | ~½ day |
| 2 | Frontend: deactivate flow modal + Workload tab in Settings → Staff | Pending | ~½ day |

**Total: ~1 working day.** Stop and report after each per Rule 9.

## Dependencies

- [update-contacts-page/](../update-contacts-page/) — REQUIRED. Provides per-entity bulk-reassign endpoints and shared `ReassignModal`.
- [update-leads-page/](../update-leads-page/) — REQUIRED. Provides `leads/bulk-reassign`.
- [update-walkins-page/](../update-walkins-page/) — REQUIRED. Provides `walk_ins/bulk-reassign`.
- [update-appointments-page/](../update-appointments-page/) — REQUIRED. Provides `appointments/bulk-reassign`.
- [update-tasks-page/](../update-tasks-page/) — REQUIRED. Provides `tasks/bulk-reassign`.
- [rbac-ownership/](../rbac-ownership/) — Done. Ownership-transfer (Owner role) lives there.

**This track must run last** — it composes endpoints from all five page tracks.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 1 modified (`users/router.py`), 1 new (`users/offboarding.py` — service orchestrating per-entity bulk-reassigns inside a single async transaction), 1 modified (`users/schemas.py` for the new request/response shapes). | No migrations needed — all underlying tables already have `assigned_to_id` after the upstream tracks. |
| Step 2 frontend | 1 new (`staff-deactivate-modal.component.ts/html`), 1 new (`staff-workload.component.ts/html`), 2 modified (`staff.page.ts/html` for the new tab + deactivate flow), 1 modified (`staff-api.service.ts`). | Reuses `ReassignModal`'s user-picker visual. |
| Tests | `tests/core/users/test_offboarding_transfer.py`. | Cases: counts endpoint, atomic transfer (rollback on failure mid-transaction), audit activity per row, Owner-deactivation blocked. |

**Total ~7 files across 2 steps.**

## Invariants this track enforces

| Rule | Where |
|---|---|
| Deactivation is atomic | All-or-nothing: if any per-entity bulk-reassign fails, the whole transaction rolls back, `is_active` stays `true`. |
| No orphans | "Skip transfer" disabled when open counts > 0. |
| Audit log per row | Reuses the per-entity audit pattern from the page tracks. |
| Owner is special | Owner is **not deactivatable** through this flow; ownership transfer is `rbac-ownership/` Step 3 territory. |
| Cross-tenant target rejected | Same as the per-entity bulk-reassign endpoints. |

## Self-check vs the 10 rules

- ✅ Rule 1 — `core/users/offboarding.py` composes Layer 1 endpoints only; no pack imports.
- ✅ Rule 2 — tenant-scoped; the transfer endpoint validates source + target are in the same `org_id`.
- ✅ Rule 6 — no new permission key (reuses `users.write` for deactivation + the per-entity `*.reassign` keys via the orchestration service running as the calling user).
- ✅ Rule 8 — 7 files; well under the limit.
- ✅ Rule 9 — stop-and-report after each.
- ✅ Rule 10 — atomic transfer ships complete; no half-done deactivation paths.

## After this track

- Offboarding a rep is one click + one transfer-target pick. No orphans, full audit.
- Workload tab gives Admin visibility into rep load — same data drives the optional list-page widgets.
- The full CRM-upgrade arc is complete: contacts → leads → walk-ins → appointments → tasks → offboarding.
