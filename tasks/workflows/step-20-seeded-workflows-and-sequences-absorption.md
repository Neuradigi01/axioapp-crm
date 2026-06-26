# Step 20 — Default workflow seeder + email_sequences absorption

**Goal:** The closing step. Two distinct landings: (1) seed the 15 default core workflows into every existing + new org so they appear in the gallery and run on the manager's spec'd events; (2) absorb `core/email_sequences/` into workflows — the existing sequence-builder UI becomes the "linear sequence" workflow type, the Settings → Email Sequences tab is removed, the existing routes redirect to the new Workflows sidebar entry. Closes the three-track plan.
**Status:** Pending
**Depends on:** Steps 1-19 (every other step shipped). Step 16 (gallery API). Module B's `tasks/automation-engine/` Step 5 (`user.signed_up`) + Step 6 (`lead.created`) + Step 10 (appointment events) + Step 11 (quote/invoice events) + Step 12 (time-based triggers). When automation-engine hasn't shipped, the seeder still installs workflows but they sit idle until events publish.

---

## Scope

### Part 1 — Seeded workflows

- `core/workflows/seeds.py` (placeholder shipped in Step 16; this step fills the bodies):
  - 15 workflow definitions (graph + metadata):
    - **Sales lifecycle (3):**
      - **New Lead Welcome + Auto-Assign**: trigger(lead.created) → routing.round_robin(pool='role:Sales') → send.email("Welcome — your dedicated rep") → flow_control.notify_user(assignee, "New lead assigned") → goal.
      - **Hot Lead Nurture (score ≥ 75)**: trigger(lead.score_threshold, conditions: gt path=lead.score value=75) → send.whatsapp(template='Hot Lead Outreach', recipient=lead.owner) → wait(1d) → wait_for_event(event=whatsapp.template_replied, max_wait=2d) → on event: send.whatsapp("Schedule a call?") → goal. On timeout: send.email("Following up") → goal.
      - **Stale Lead Recovery (30d/60d/90d)**: trigger(lead.stale_30d) → branch(by lead.last_activity_age_days; cases: ≤30 → recovery email A; ≤60 → recovery email B + Slack alert owner; >90 → archive + Slack notify owner). re_enrollment='never' (allows multiple concurrent for the 30/60/90 ticks).
    - **Quotes & invoices (3):**
      - **Quote Follow-Up (3-touch)**: trigger(quote.sent) → wait(2d) → wait_for_event(event=quote.viewed, max_wait=5d) → on event: send.email("Glad you saw it") → goal. On timeout: send.email("Touching base on the quote") → wait(3d) → wait_for_event(quote.viewed, max_wait=5d) → on event: goal; on timeout: send.email("Last chance — quote expires soon") → goal.
      - **Quote Accepted Thank-You**: trigger(quote.accepted) → send.email("Thank you!") → record.create_task(title='Send onboarding pack', assignee=lead.owner, due=+2d) → lifecycle.mark_converted → goal.
      - **Invoice Overdue Escalation (7d/14d/30d)**: trigger(invoice.overdue_7d) → send.email("Friendly reminder"). trigger(invoice.overdue_14d) → send.email + send.whatsapp. trigger(invoice.overdue_30d) → send.email + Slack notify owner + record.create_task(assignee=Owner, "Personal collection call"). Each is a separate workflow (three workflows total) so re-enrollment can be `never` per overdue interval.
    - **Customer onboarding (2):**
      - **New Customer Welcome (5-touch over 30d)**: trigger(lifecycle.mark_converted) → send.email("Welcome aboard") → wait(3d) → send.email("First-month tips") → wait(7d) → send.email("Schedule your 30-day review") → wait(20d) → record.create_appointment(type='30-day review') → goal.
      - **Post-Purchase Feedback + Review Request**: trigger(order.delivered) → wait(7d) → send.email("How was it?") → wait_for_event(email.replied, max_wait=14d) → on event: send.email("Glad to hear it! Could you leave a review?" with review-link) → goal. On timeout: goal.
    - **Engagement (3):**
      - **Birthday + Anniversary Greetings**: trigger(contact.birthday) → send.email("Happy Birthday!") + send.whatsapp("Happy Birthday from <org>") → goal. Same shape for contact.anniversary.
      - **Re-engagement (inactive 90d)**: trigger(contact.last_active_90d_ago — published by a daily sweep) → send.email("We miss you!") → wait(7d) → wait_for_event(email.opened, max_wait=14d) → on event: send.email("Here's what's new") → goal. On timeout: tagging.add_tag(tag='inactive') → goal.
      - **Repeat-Purchase Nurture**: trigger(order.placed, conditions: gt path=contact.orders_count value=1) → send.email("Loyal customer reward") → goal.
    - **Walk-in (1):**
      - **Walk-In Follow-Up**: trigger(walk_in.registered) → wait(1h) → send.whatsapp("Thanks for visiting! Here's the catalog you asked about") → wait_for_event(quote.sent, max_wait=7d) → on event: goal. On timeout: notify owner.
    - **Internal/team (3):**
      - **New Team Member Onboarding**: trigger(user.signed_up via invite_accepted) → notify Owner → wait(1d) → send.email(to new user, "Day 1 resources") → wait(2d) → send.email("Day 3 walkthrough") → goal.
      - **Deal Won Slack Alert**: trigger(quote.accepted, conditions: gt path=quote.total_amount value=100000) → send.slack(channel='#deals', message="{{user.full_name}} closed {{quote.total_amount}} 🎉") → goal.
      - **Daily Digest to Sales Manager (recurring 9am IST)**: trigger(time.daily_tick, condition: org_local_time=='09:00') → notify_user(role:Manager, body="Today's pipeline summary…") → goal. The pipeline-summary text is rendered from a template that pulls live stats.

  - Each definition includes `gallery_visible: true` so they appear in Step 16's gallery + `is_marketing` set correctly per use case.

- `core/tenants/provisioning.py` extended — `on_org_created` hook now calls `workflows.seeds.install_seeded_workflows(session, org_id)`. Already-existing orgs get the seeds via a one-shot backfill migration `<ts>_bf_workflow_seeds.py` that iterates every org + idempotently installs.

- Seeds are installed as **draft** workflows. Operator must review + activate per the manager's safety preference (no auto-active marketing workflows).

### Part 2 — email_sequences absorption

- `core/email_sequences/` — the existing module is DEPRECATED + thin-shimmed:
  - Module REMAINS importable (for backward compatibility during transition); every public function becomes a thin shim over `core/workflows/`.
  - `email_sequences.service.enroll(...)` → calls `workflows.engine.start_run` against a "Linear Email Sequence" workflow type.
  - At install time, every existing `tbl_email_sequences` row is migrated into a `tbl_workflows` row of type "linear sequence" with the equivalent graph (trigger → wait → send → wait → send → ...).
  - The old `tbl_email_sequences` + `tbl_email_sequence_steps` + `tbl_email_sequence_enrollments` tables stay readable for one release (for historical-data dashboards); new enrollments only land in `tbl_workflow_runs`.

- Frontend:
  - Settings → Email Sequences tab REMOVED from `settings-page.html`.
  - Routes `/user/settings/email-sequences/*` redirect to `/user/workflows?category=Marketing`.
  - `sequence-builder.component` (existing) is moved into `core/workflows/canvas/sequence-builder-view.component` — when a workflow's type is "linear sequence" (i.e. graph has only trigger / wait / send nodes, no branches), the canvas page offers a "Switch to sequence view" toggle that renders the old vertical sequence-builder UI. Operators who prefer the linear list keep using it; operators who want branches switch to canvas mode.

- The `core/email_sequences/scheduler.py` Celery task — converted to a no-op (the workflow engine + beat sweep now drive sequence runs).

### Part 3 — track-close housekeeping

- `tasks/automation-engine/README.md` + `tasks/template-library/README.md` updated to reference the workflows track as the live destination for sequence + multi-step automation.

- `CLAUDE.md` — add a one-paragraph note that Module C is live, and that the locked three-track plan is complete.

Out of scope:

- Vertical-pack workflows (Furniture: Showroom Visit Thank You, Custom Order Confirmation, Warranty Reminder, Festival Sale) — those land via `packs/furniture/pack.yaml` in the eventual furniture pack track. Step 20 only ships core.
- Removing the legacy `tbl_email_sequences` tables — kept readable for one release; cleanup migration in a follow-up.
- AI-suggested workflow customizations — v2.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/seeds.py` | edit — fill in the 15 workflow graphs |
| `API/alembic/versions/<ts>_bf_workflow_seeds.py` | **NEW** — backfill existing orgs |
| `API/src/app/core/tenants/provisioning.py` | edit — call `install_seeded_workflows` on org create |
| `API/src/app/core/email_sequences/service.py` | edit — shim over workflows engine |
| `API/src/app/core/email_sequences/scheduler.py` | edit — no-op (work moves to workflows) |
| `API/alembic/versions/<ts>_migrate_sequences_to_workflows.py` | **NEW** — data migration |
| `APP/src/app/features/user/core/settings/settings-page.html` | edit — remove sequences tab |
| `APP/src/app/features/user/user.routes.ts` | edit — redirect old sequence routes |
| `APP/src/app/features/user/core/workflows/canvas/sequence-builder-view.component.{ts,html}` | **NEW** — wraps existing sequence-builder UI |
| `APP/src/app/features/user/core/workflows/canvas/workflow-canvas.page.{ts,html}` | edit — "Switch to sequence view" toggle for linear workflows |
| `CLAUDE.md` | edit — three-track complete note |
| `tasks/automation-engine/README.md` | edit — link to workflows |
| `tasks/template-library/README.md` | edit — link to workflows |
| `API/tests/workflows/test_seeds.py` | **NEW** |
| `API/tests/workflows/test_sequences_absorption.py` | **NEW** |

**~15 files. ~1000 lines.** Large step because two semantically distinct landings (seeds + absorption) both must happen for the track to close cleanly.

## Plan

1. seeds.py — 15 workflow graphs as Python dicts (each ~50 lines). Mirror the gallery catalog from Step 16.
2. Backfill migration — iterates every org, idempotently calls install for any missing seeds.
3. Provisioning hook — on_org_created installs seeds.
4. email_sequences shim — service functions wrap workflows engine; scheduler tick becomes no-op.
5. Data migration — every `tbl_email_sequences` row → equivalent `tbl_workflows` row.
6. Frontend — removed sequences tab, redirected routes, embedded sequence-builder view.
7. Tests: seed installer idempotent; legacy sequence-builder still renders for linear workflows; switching to canvas view shows the same content as a graph.

## DB changes / migrations

Two migrations:
- `<ts>_bf_workflow_seeds.py` — backfill seeded workflows into existing orgs.
- `<ts>_migrate_sequences_to_workflows.py` — convert email sequence rows to workflow rows.

Both reversible (downgrades archive the seed rows + restore the original sequence rows).

## Tests

12 pytest + 4 Jest cases:

- (pytest) install_seeded_workflows creates 15 draft rows in a fresh org.
- (pytest) Re-running install_seeded_workflows is idempotent.
- (pytest) Each seed has the documented re_enrollment_rule (mostly `once`; stale-lead uses `never`; daily-digest uses `daily`).
- (pytest) Backfill migration installs into every existing org.
- (pytest) email_sequences.service.enroll calls workflows.engine.start_run.
- (pytest) Data migration converts a 3-step sequence to a workflow with 5 nodes (trigger + send + wait + send + wait + send + goal).
- (pytest) Old sequence row count after migration = 0 newly-enrolled; existing-enrollments preserved.
- (pytest) `on_org_created` provisioning hook installs seeds.
- (pytest) Seeded workflows visible in `GET /workflows/gallery`.
- (pytest) Seeded workflows have correct trigger event_types.
- (pytest) Daily-Digest workflow has the daily re-enrollment rule.
- (pytest) Walk-In Follow-Up workflow uses contact_id from the trigger payload.
- (Jest) Sequences tab removed from Settings.
- (Jest) Old /user/settings/email-sequences redirects to /user/workflows.
- (Jest) Linear workflows show "Switch to sequence view" toggle.
- (Jest) Non-linear workflows do NOT show the toggle.

## Smoke

```
1. Provision a fresh org → 15 workflows appear in /user/workflows (all Draft).
2. /user/workflows/gallery → 15 cards visible.
3. Activate "New Lead Welcome + Auto-Assign" → status=Active.
4. publish lead.created → run starts → routing picks an owner → email sent.
5. /user/settings → no Email Sequences tab.
6. Browse to /user/settings/email-sequences (old URL) → redirects to /user/workflows?category=Marketing.
7. Existing sequences appear as "Linear sequence" workflows in the list.
8. Click one → canvas page → "Switch to sequence view" toggle visible → click → vertical builder UI (the old sequences UX).
9. Switch back to canvas → see same content as a graph.
```

## Risks

- Backfilling 15 workflows into hundreds of orgs is a write-heavy migration. Mitigation: batch by org, 50 orgs per transaction. Monitor on staging before production.
- Data migration of existing sequences with mid-flight enrollments — preserve enrollments untouched (linked to old sequence row), but new enrollments go to the workflow. Document the parallel state for one release.
- Operators expecting Settings → Email Sequences tab will land on the redirect. UX: the redirect carries a one-time toast "Email Sequences are now Workflows! Filter to Marketing to find your sequences."
- Vertical-pack workflows (Furniture) are out of scope — verify the pack.yaml `workflows` section docs are clear so the furniture-pack track can add them without confusion.

## Self-check (10 rules)

`core/workflows/` + tenants provisioning + email_sequences absorb + tiny frontend. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ Sidebar registered upstream. Permissions enforced. pack.yaml NOT touched here — only the CORE seeds (lead lifecycle, sales, customer onboarding, engagement, walk-in, internal). Vertical-pack workflows are a future furniture-pack track. ✓ 15 files / ~1000 lines — large but justified (track-close + dual landing). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 20 — Default workflow seeder + email_sequences absorption
Files: 15
Verify: 15 seeded workflows install into every org as drafts; gallery shows them; sequences absorbed (Settings tab gone, old routes redirect, linear workflows offer the legacy view).
Tests: 12 pytest + 4 Jest.

Track complete: 20 steps shipped. Module C (Workflows) operational. Templates → Automation → Workflows pipeline live end-to-end. Three-track plan locked by the manager on 2026-06-25 is fully delivered.

Awaiting "proceed" — and a celebration.
```
