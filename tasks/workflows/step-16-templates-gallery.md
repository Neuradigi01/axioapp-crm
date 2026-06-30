# Step 16 — Templates gallery + clone-from-default

**Goal:** A "Browse templates" surface where operators see the 15 default seeded workflows (Step 20) and clone any of them into their library. Modeled on HubSpot's workflow-templates gallery.
**Status:** COMPLETED — NEW `API/src/app/core/workflows/templates_gallery.py` ships the 15-entry catalogue as immutable `CATALOG: tuple[GalleryTemplate, ...]` (Sales=3, Quotes & invoices=3, Customer onboarding=2, Engagement=3, Walk-in=1, Internal=3 = 15). `GalleryTemplate` dataclass exposes `id` / `name` / `description` / `category` / `channels[]` / `goal_node_label` / `est_setup_time_minutes` / `est_completion_rate_pct` / `screenshot_url` / `graph_preview` / `is_marketing` / `re_enrollment_rule`. `_placeholder_graph(trigger_event_type, send_actions, goal_label)` factory builds a minimal `trigger → send-action(s) → flow_control.goal` graph per entry (Step 20 will replace these with real graphs; placeholders make the gallery inspectable from day one). Public API: `list_gallery()` returns the dict-serialised catalogue, `get_template(id)` resolves by id, `clone_from_gallery(session, *, org_id, user_id, template_id, name, folder_id)` calls into `workflows_service.create_workflow` after running `_strip_send_template_ids(graph)` — every `send.*` + `record.create_*` node has its `template_id` removed and `__valid=false` stamped so the Step-15 editor lights the red validation dot until the operator picks a template per node. Name handling: defaults to `Copy of <template_name>`, auto-uniqifies with `(2)`, `(3)`, … via `_next_unique_name(base, existing)` + `_existing_names_in_org` DAL helper; even an operator-supplied duplicate name is silently bumped on `DuplicateWorkflowName` retry (matches the spec's "idempotent on duplicate name" requirement). `core/workflows/data_access.py` extended with `list_workflow_names(session, org_id) -> list[str]` so the auto-uniqify avoids N+1 retry loops. NEW `core/workflows/seeds.py` ships a no-op `seed_default_workflows(session, org_id, user_id)` placeholder Step 20 will fill in — module path is stable ahead of Step 20 so dependent imports don't churn. `core/workflows/router.py` extended with two endpoints: `GET /api/v1/workflows/gallery` (gated on `workflows.read`, returns `WorkflowGalleryListResponse` with `items + total`) and `POST /api/v1/workflows/gallery/{template_id}/clone` (gated on `workflows.clone`, `WorkflowGalleryCloneRequest` body with optional `name + folder_id`, 404 on unknown `template_id`, 409 mapped via `_workflow_http_map` on `DuplicateWorkflowName` after the auto-uniqify retry path, 201 with `WorkflowRead` body on success). NEW `API/tests/workflows/test_gallery_clone.py` ships 5 pytest cases: (1) `len(list_gallery()) == 15` with unique ids + non-empty graph_preview; (2) clone creates `status=draft` + carries node/edge counts from the catalogue; (3) cloned send nodes have `template_id` absent + `__valid=false` stamped; (4) duplicate-name collision auto-suffixes (`Quote Follow-Up` → `Quote Follow-Up (2)`); (5) `is_marketing` flag carried from catalogue entry — `lead.welcome_auto_assign` lands marketing=true, `internal.deal_won_alert` lands marketing=false. Frontend: `workflows-api.service.ts` extended with `WorkflowGalleryEntry` / `WorkflowGalleryListResponse` / `WorkflowGalleryCloneRequest` types + `listGallery()` GET + `cloneFromGallery(id, payload)` POST. `user.routes.ts` adds `path: 'workflows/gallery'` (gated on `workflows.read`, lazy-loads `WorkflowsGalleryPageComponent`); placed BEFORE the `workflows/new` and `workflows/:id` routes so the literal string matches first. NEW `gallery/workflows-gallery.page.{ts,html}` is the HubSpot-style card grid: header bar with Back + "Skip — start blank" CTAs, error banner, category-tab row (All templates + dynamic tabs from `categories()` computed signal), 4-column responsive grid (`grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4`), each card shows category chip + Lucide Clock with setup-time estimate + name + description + channel chips (sky-50 pills) + goal label + Lucide TrendingUp with completion-rate (emerald-700), Preview + "Use this template" buttons. `openPreview(entry)` swaps in `<app-gallery-preview-modal>`; `startClone(entry)` closes the preview and swaps in `<app-clone-name-modal>`; `confirmClone({name})` POSTs to the clone endpoint and `router.navigate(['/user/workflows', workflow.id])` lands the operator straight in the canvas editor. NEW `gallery/preview.modal.component.{ts,html}` provides its own `CanvasStateService` (component-scoped DI), loads the gallery entry's `graph_preview` via a `synthetic: WorkflowRead` object, computes a `viewBox` from node bounding-box + 60px padding, renders the same `WorkflowNodeComponent` + `WorkflowEdgeComponent` SVG primitives the editor uses but without drag handlers — pure read-only viewer. Footer "Use this template" re-emits up to the parent. NEW `gallery/clone-name.modal.component.{ts,html}` is the naming form: text input pre-seeded from `Copy of <entry.name>` via an `effect()`, 120-char max-length, Cancel + Create-draft buttons (Create disabled + button text → "Creating…" during the post). Empty input falls back to the `defaultName()` so the operator can hit Enter without typing anything. Step 13 list page wired: two "Start from template" CTAs (header + empty-state) now `routerLink="/user/workflows/gallery"` instead of `/user/workflows/new`. Smoke verified via backend import-check: `templates_gallery` + `seeds` + `router` import cleanly; `CATALOG` returns exactly 15 entries. Pytest run deferred per `feedback_pause_before_pytest.md`. Jest specs deferred — frontend test infra not yet wired up in this repo (same disposition as Step 14/15).
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
