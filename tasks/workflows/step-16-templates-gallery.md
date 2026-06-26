# Step 16 — Templates gallery + clone-from-default

**Goal:** A "Browse templates" surface where operators see the 15 default seeded workflows (Step 20) and clone any of them into their library. Modeled on HubSpot's workflow-templates gallery.
**Status:** Pending
**Depends on:** Step 3 (clone endpoint + permission `workflows.clone`). Step 13 (workflows list page with "Start from template" CTA).

---

## Scope

In-scope:

- Backend:
  - `core/workflows/templates_gallery.py` — exposes the seeded workflows as a read-only catalog. Each entry: `{id, name, description, category, channels[], goal_node_label, est_setup_time_minutes, est_completion_rate_pct, screenshot_url, graph_preview}`. Returns the same 15 workflows Step 20 seeds; this step provides the catalog interface.
  - `GET /api/v1/workflows/gallery` — returns the catalog (org-agnostic; same list for everyone). Gated on `workflows.read`.
  - `POST /api/v1/workflows/gallery/{template_id}/clone` body `{name?: str, folder_id?: UUID}` — copies the gallery template's graph into a new draft workflow in the org's library, with the operator-supplied name (defaults to "Copy of <template name>"). Returns the new workflow row. Gated on `workflows.clone`.

- Frontend:
  - `app/src/app/features/user/core/workflows/gallery/workflows-gallery.page.{ts,html}` — URL `/user/workflows/gallery`. Category filter (Sales / Marketing / Service / Customer onboarding / Internal). Card grid. Each card: name + description + category chip + estimated setup time + "Preview" + "Use this template" CTAs.
  - `app/src/app/features/user/core/workflows/gallery/preview.modal.component.{ts,html}` — read-only canvas preview (reuses Step 14 canvas components in read-only mode). Click "Use this template" → opens a small naming modal → POST clone → navigate to the new workflow's canvas (Step 14 page).
  - "Start from template" CTA on the workflows list page (Step 13) now routes to `/user/workflows/gallery`.

- Default workflows seeded (Step 20 wires the actual graphs; Step 16 just catalogs them):

  **Sales lifecycle (3):**
  - New Lead Welcome + Auto-Assign
  - Hot Lead Nurture (score ≥75)
  - Stale Lead Recovery (30d / 60d / 90d branches)

  **Quotes & invoices (3):**
  - Quote Follow-Up (3-touch)
  - Quote Accepted Thank-You
  - Invoice Overdue Escalation (7d / 14d / 30d)

  **Customer onboarding (2):**
  - New Customer Welcome (5-touch over 30d)
  - Post-Purchase Feedback + Review Request

  **Engagement (3):**
  - Birthday + Anniversary Greetings
  - Re-engagement (inactive 90d)
  - Repeat-Purchase Nurture

  **Walk-in (1):**
  - Walk-In Follow-Up

  **Internal/team (3):**
  - New Team Member Onboarding
  - Deal Won Alert (Slack)
  - Daily Digest to Sales Manager (recurring 9am IST org tz)

- Each gallery entry's `graph` field is a serialized workflow graph (same shape as `tbl_workflows.graph`) so the clone endpoint can copy verbatim. Template IDs referenced in send actions are RESOLVED at clone time — the gallery lists template names by category/channel; the operator's org may not have those templates yet, so the cloned workflow's send actions land with `template_id=null` + a validation marker so the operator picks one before activating.

- Vertical-pack workflows (future furniture pack) will register additional gallery entries via `pack.yaml`; the gallery endpoint returns the merged list (core + installed pack).

Out of scope:

- "Create a workflow template" (operators publish their own templates) — deferred to v2.
- Marketplace (operators import templates from other orgs) — deferred.
- Default workflows that depend on un-shipped modules (e.g. event-spam-prevention) — only 15 core workflows ship.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/templates_gallery.py` | **NEW** — catalog + clone-from-gallery logic |
| `API/src/app/core/workflows/router.py` | edit — gallery list + clone endpoints |
| `API/src/app/core/workflows/seeds.py` | **NEW** — placeholder; Step 20 fills in the 15 graphs |
| `APP/src/app/features/user/core/workflows/gallery/workflows-gallery.page.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/gallery/preview.modal.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/gallery/clone-name.modal.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/workflows-api.service.ts` | edit — gallery + clone-from-gallery wrappers |
| `APP/src/app/features/user/user.routes.ts` | edit — /user/workflows/gallery route |
| `API/tests/workflows/test_gallery_clone.py` | **NEW** |
| `APP/src/app/features/user/core/workflows/gallery/workflows-gallery.page.spec.ts` | **NEW** |

**~10 files. ~500 lines.**

## Plan

1. Backend gallery catalog + endpoints.
2. seeds.py placeholder (Step 20 fills the graphs).
3. Gallery page + preview modal + clone-name modal.
4. Routes + api service.
5. Tests: gallery list returns 15 entries; clone creates draft + copies graph; nullified template_ids surface as validation issues.

## DB changes / migrations

None.

## Tests

5 pytest + 3 Jest cases:

- (pytest) `GET /workflows/gallery` returns 15 entries.
- (pytest) `POST /workflows/gallery/{id}/clone` creates a draft + carries over the graph.
- (pytest) Cloned workflow's send-action node has `template_id=null` (operator picks at clone time).
- (pytest) Clone respects re-enrollment + ab_sibling defaults from gallery.
- (pytest) Gallery clone idempotent on duplicate name — appends "(2)" suffix.
- (Jest) Gallery page renders 15 cards.
- (Jest) Preview modal opens read-only canvas.
- (Jest) Clone modal POSTs + navigates to /user/workflows/:id.

## Smoke

```
1. /user/workflows → click "Start from template" → /user/workflows/gallery.
2. 15 cards visible across category tabs.
3. Click "New Lead Welcome" → preview modal opens with read-only canvas showing the graph.
4. Click "Use this template" → modal asks for name → enter "Diwali Lead Welcome" → submit.
5. Navigated to /user/workflows/<new-id> in canvas mode.
6. Send-action nodes show validation markers because template_id=null.
7. Operator picks a template per send node → markers clear → save → activate.
```

## Risks

- Catalog drift if Step 20's seeds are updated without updating the gallery catalog. Mitigation: the gallery list is derived from the seeds module's data — single source.
- Clone endpoint is the most-likely path for operators to land on broken workflows (missing template references). The validation markers in Step 15 already cover this; gallery page just adds a one-line hint.

## Self-check (10 rules)

`core/workflows/` + frontend. ✓ org_id transparent for clone (operator's org). ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced. pack.yaml untouched (this step's catalog is core-only; pack entries register additively in the future). ✓ 10 files / ~500 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 16 — Templates gallery + clone-from-default
Files: 10
Verify: gallery page shows 15 default workflows; preview modal renders read-only canvas; clone creates draft + carries graph; template_id null on send actions until operator picks.
Tests: 5 pytest + 3 Jest.
Awaiting "proceed".
```
