# Step 21 — System-default auto-active workflows

**Goal:** Promote 3 seeded workflows from "draft" to system-default + auto-active so a brand-new org boots into a *functioning* CRM (leads auto-triaged, big wins announced, daily digest delivered) without operator setup — matching the industry baseline (Salesforce Lead Assignment Rules + Big Deal Alert, HubSpot Inbox round-robin, Zoho Lead Assignment Rules, Pipedrive Lead Distribution).
**Status:** COMPLETED
**Depends on:** Step 20 (seeder + 15 catalog entries + provisioning hook). Step 7-11 (every action handler the new graph uses already shipped).

---

## Scope

### Part 1 — System-default flag

- Migration `0146_workflow_system_default`: add `is_system_default BOOLEAN NOT NULL DEFAULT false` to `tbl_workflows`. Reversible.
- `Workflow` ORM model: `is_system_default: Mapped[bool]` column.
- `WorkflowRead` schema surfaces the flag so the frontend can render a "System" badge.

### Part 2 — Catalog flags + Lead Auto-Triage rewrite

- `GalleryTemplate` dataclass gains 2 fields:
  - `auto_activate: bool = False` — seeder installs `status='active'` (vs default `draft`).
  - `is_system_default: bool = False` — seeder stamps the column; service refuses delete/archive.
- Three catalog entries flipped to `auto_activate=True, is_system_default=True`:
  - **New Lead Auto-Triage** (renamed from "New Lead Welcome + Auto-Assign", graph rewritten — see below).
  - **Deal Won Slack Alert** (internal-only, fires on `quote.accepted` over threshold).
  - **Daily Digest to Sales Manager** (recurring 9am IST, internal email).

The other 12 catalog entries keep `auto_activate=False` (contact-facing marketing flows, operator activates after picking templates per compliance gate).

### Part 3 — Lead Auto-Triage full graph

Replace the placeholder "New Lead Welcome + Auto-Assign" graph with a real 10-node intake flow:

```
trigger(lead.created)
  → branch.switch by lead.source         # paid_ad / web_form / import / manual
  → branch.switch by lead.score          # ≥75 → senior pool, else regular pool
  → routing.round_robin(pool='Sales')
  → record.update_lead_field             # status='new', assigned_to_id, first_touch_at
  → record.update_contact_field          # contact.assigned_to_id = same rep
  → tagging.add_tag                      # priority + source tags
  → flow_control.notify_user(assignee)   # in-app + email + push
  → branch.switch (score≥90 OR priority=high)
       → send.slack(channel='#sales-hot-leads', "...")
  → record.create_task                    # follow-up, due +1 day
  → flow_control.goal "Lead triaged"
```

All node types already registered (Steps 7-11 shipped them). No new action handlers needed.

### Part 4 — Seeder honours flags

- `seeds.install_seeded_workflows` reads `entry.auto_activate` + `entry.is_system_default`:
  - When `auto_activate=True` → install with `status=WorkflowStatus.active` instead of `draft`.
  - When `is_system_default=True` → stamp `workflow.is_system_default=True`.
- Existing idempotency unchanged.

### Part 5 — Service guards

- `workflows_service.archive_workflow` refuses on system-default rows (raises `WorkflowLocked`).
- Hard delete (if added later) similarly refused.
- Pause + edit + activate-after-pause remain allowed (operator can tune cadence without dropping the safety net).

### Part 6 — Frontend

- List page: "System" badge next to system-default rows.
- Row menu: hide Archive on system-default rows.
- Canvas page: small system-default chip in header.

### Part 7 — Backfill for existing 24 orgs

- One-shot script (via docker exec) that, per org:
  - Updates the 3 system-default seed rows to `status='active', is_system_default=true`.
  - Replaces the Lead Auto-Triage row's graph with the new 10-node version.
- Idempotent (re-runnable).

### Part 8 — Tests

10 pytest cases:

- Migration up/down round-trip.
- Seeder installs system-default rows as `status='active', is_system_default=true`.
- Non-system-default seeds still install as `draft`.
- Seeder re-run is idempotent (system-default rows aren't duplicated).
- `archive_workflow` refuses on system-default rows.
- `archive_workflow` succeeds on regular rows.
- `create_organization` flips the 3 defaults active immediately.
- Lead Auto-Triage graph has correct node count + trigger event_type.
- Switch nodes have the expected branch labels.
- Tagging + routing + record nodes carry expected config keys.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/0146_workflow_system_default.py` | **NEW** |
| `API/src/app/core/workflows/models.py` | edit — `is_system_default` column |
| `API/src/app/core/workflows/schemas.py` | edit — `WorkflowRead.is_system_default` |
| `API/src/app/core/workflows/templates_gallery.py` | edit — dataclass fields + rewrite 1 graph + flip 3 entries |
| `API/src/app/core/workflows/seeds.py` | edit — honour flags |
| `API/src/app/core/workflows/service.py` | edit — guard archive on system defaults |
| `APP/src/app/features/user/core/workflows/workflows-api.service.ts` | edit — surface `is_system_default` on `WorkflowRead` |
| `APP/src/app/features/user/core/workflows/workflows.page.html` | edit — System badge + hide archive on system rows |
| `API/tests/workflows/test_system_default.py` | **NEW** — 10 pytest cases |
| `tasks/workflows/step-21-system-default-workflows.md` | spec (this file) |
| `tasks/workflows/README.md` | edit — add Step 21 row |

**~9 files. ~600 lines.**

## DB changes / migrations

One migration. Reversible. Backfill is a separate one-shot script (no migration needed since it's idempotent + safe to re-run).

## Smoke

```
1. Run migration → tbl_workflows.is_system_default column exists.
2. Run backfill → 3 rows × 24 orgs become active + is_system_default=true.
3. POST /tenants (or use the signup flow) → 16th workflow row in DB confirms; verify 3 of the seeds installed active.
4. /user/workflows → 3 rows show "System" badge + no Archive option.
5. Try DELETE /workflows/{system_default_id} → 409 WorkflowLocked.
6. publish lead.created → Lead Auto-Triage fires → run started, rep assigned, task created, notification fired.
```

## Risks

- Existing orgs' Lead Auto-Triage rows were seeded with the placeholder graph; the backfill replaces them. If an operator already customised the seed row, the backfill overwrites their edits. Mitigation: backfill only replaces if `current_version == 1` (i.e. operator hasn't saved a new version).
- Auto-active workflows fire immediately on first matching event. The 3 system defaults are internal-only by design — no contact-facing sends. Verified per node-type in scope.
- "System" badge UX: pause is allowed; delete is not. Operator can effectively disable the system default by pausing it. Document.

## Self-check (10 rules)

`core/workflows/` + tiny frontend + 1 column migration. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar untouched. Permissions untouched (system-default flag is metadata, doesn't change RBAC). pack.yaml untouched. ✓ 9 files / ~600 lines. ✓ Stop-report. ✓ No TODOs.

## Stop & report

```
Step 21 — System-default auto-active workflows
Files: 9
Verify: 3 system-default seeds install active in new orgs + flipped active on existing 24 orgs; "System" badge renders; archive blocked on system rows.
Tests: 10 pytest.
Awaiting "proceed".
```
