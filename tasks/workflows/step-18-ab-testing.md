# Step 18 — A/B test entire workflows + winner selection

**Goal:** Two-workflow A/B testing. Operator picks an "A" workflow + builds a "B" variant; at enrollment, the engine 50/50 splits contacts between them. After a configurable hold-back window, the engine picks the winner by goal-conversion rate and auto-promotes (loser archived, winner activated).
**Status:** Pending
**Depends on:** Step 5 (`_split_for_ab` placeholder shipped). Step 11 (`goal` node — drives the conversion metric). Step 19's analytics aren't required for this — A/B uses a simpler local rate calculation.

---

## Scope

In-scope:

- Backend:
  - `core/workflows/ab_testing.py`:
    - `enroll_with_ab_split(workflow: Workflow, *, contact_id) -> Workflow` — when `workflow.ab_sibling_id` is set, deterministically picks A or B based on `(contact_id, workflow.id)` hash so a contact gets the same variant if re-enrolled.
    - `pick_winner(session, *, org_id, a_workflow_id, b_workflow_id) -> dict` — runs the conversion-rate calc: `goal_reached_runs / total_started_runs` per variant + a Z-test for statistical significance (minimum 50 runs per variant + p < 0.05 for confidence). Returns `{winner: 'a' | 'b' | 'inconclusive', a_rate, b_rate, p_value, sample_size_a, sample_size_b}`.
    - `auto_promote(session, *, winner_workflow_id, loser_workflow_id, user_id)` — winner.status='active', loser.status='archived', writes an audit entry on both ("auto-promoted by A/B test"). Loser keeps existing runs to completion (no mid-stream cancellation).

  - `tbl_workflows` columns added (migration `<ts>_workflow_ab_columns.py`):
    - `ab_paired_workflow_id` UUID self-FK SET NULL (the bidirectional sibling — A.ab_paired = B.id AND B.ab_paired = A.id).
    - `ab_test_started_at` timestamptz nullable.
    - `ab_test_holdback_until` timestamptz nullable.
    - `ab_test_winner_metric` enum (`goal_conversion | reply_rate | open_rate | custom`) default `goal_conversion`.
    - `ab_test_min_runs_per_variant` int default 50.
    - `ab_test_winner_workflow_id` UUID nullable (set after `pick_winner` completes).
    - `ab_test_decided_at` timestamptz nullable.

  - Service-layer methods:
    - `service.pair_for_ab(session, *, workflow_id, sibling_id, holdback_seconds, metric)` — pairs two existing draft workflows. Both must be drafts; both must have the same trigger event_type; both must have a goal node. Sets `ab_test_started_at` AND `ab_test_holdback_until = now + holdback`. Activates both.
    - `service.unpair_ab(session, *, workflow_id)` — operator-initiated early cancel. Both workflows stay active but the split stops; new enrollments go to the original A workflow.

  - Beat task `workflows.evaluate_ab_winners()` — hourly. Picks workflows whose `ab_test_holdback_until < now()` AND `ab_test_decided_at IS NULL`; calls `pick_winner` + `auto_promote` if winner is clear; emails the workflow owner about the decision via `notifications.notify`. If inconclusive, extends the holdback by 50% (max 30 days total).

  - Endpoints:
    - `POST /api/v1/workflows/{id}/pair-ab` body `{sibling_id, holdback_seconds, metric}`. `workflows.write`.
    - `POST /api/v1/workflows/{id}/unpair-ab`. `workflows.write`.
    - `GET /api/v1/workflows/{id}/ab-stats` — returns live conversion rates + p-value. `workflows.view_analytics`.

- Frontend:
  - `app/src/app/features/user/core/workflows/ab/ab-pair-modal.component.{ts,html}` — opens from canvas header "Run A/B test"; lets operator pick the B sibling (must be a draft with same trigger), set holdback duration (1d / 3d / 7d / 14d / 30d), select metric.
  - `app/src/app/features/user/core/workflows/ab/ab-stats-banner.component.{ts,html}` — banner on canvas header while a workflow is in an active A/B test. Shows live conversion rates, sample sizes, time-until-decision. Pulses if a winner has been called.
  - `app/src/app/features/user/core/workflows/ab/ab-comparison.page.{ts,html}` — full-page side-by-side of A vs B (graphs, key metrics, daily-rate sparklines). URL `/user/workflows/:id/ab-compare`. Linked from the banner + the list page.

Out of scope:

- Multi-variant tests (A/B/C/D) — v2 polish; v1 is two-variant only.
- "Promote loser to control + keep winner as new A" — operators manually clone the winner if they want to keep iterating.
- Mid-test pause + resume — once paired, the test runs to completion (or unpair, which cancels the test).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_workflow_ab_columns.py` | **NEW** — 7 ALTER ADD COLUMN |
| `API/src/app/core/workflows/models.py` | edit — A/B columns |
| `API/src/app/core/workflows/schemas.py` | edit — A/B schemas |
| `API/src/app/core/workflows/ab_testing.py` | **NEW** |
| `API/src/app/core/workflows/service.py` | edit — pair / unpair functions |
| `API/src/app/core/workflows/router.py` | edit — 3 new endpoints |
| `API/src/app/core/workflows/tasks.py` | edit — `evaluate_ab_winners` Celery task |
| `API/src/celery/celery_config.py` | edit — `workflows-evaluate-ab` beat at `crontab(minute='*/60')` |
| `API/src/app/core/workflows/trigger_handlers.py` | edit — call `enroll_with_ab_split` instead of placeholder |
| `APP/src/app/features/user/core/workflows/ab/ab-pair-modal.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/ab/ab-stats-banner.component.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/ab/ab-comparison.page.{ts,html}` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — /user/workflows/:id/ab-compare route |
| `API/tests/workflows/test_ab_testing.py` | **NEW** |

**~14 files. ~800 lines.**

## Plan

1. Migration with 7 ALTER ADD COLUMN.
2. ab_testing.py module — split / pick_winner / auto_promote.
3. Service pair / unpair.
4. Router endpoints.
5. Beat task + autodiscover registration.
6. Trigger-handler patch to call `enroll_with_ab_split`.
7. Frontend: pair modal + stats banner + comparison page.
8. Tests: deterministic split; winner picked correctly with sample data; inconclusive extends holdback.

## DB changes / migrations

One migration with 7 ALTER COLUMNs. Reversible.

## Tests

12 pytest + 2 Jest cases:

- (pytest) Deterministic split: same `(contact_id, workflow_id)` always picks the same variant.
- (pytest) 50/50 distribution over 1000 enrollments.
- (pytest) `pick_winner`: 200/1000 vs 250/1000 → winner='b' with significant p-value.
- (pytest) `pick_winner`: 50/100 vs 51/100 → winner='inconclusive'.
- (pytest) `pick_winner`: sample below min_runs_per_variant → winner='inconclusive'.
- (pytest) `auto_promote` archives loser + keeps existing runs.
- (pytest) `pair_for_ab` refuses if triggers differ.
- (pytest) `pair_for_ab` refuses if either side missing goal node.
- (pytest) Beat task picks winners + extends holdback if inconclusive.
- (pytest) Owner notified on decision.
- (pytest) `unpair_ab` stops the split; subsequent enrollments go to A.
- (pytest) `ab-stats` endpoint returns live rates.
- (Jest) Pair modal validates sibling-must-be-draft + same-trigger.
- (Jest) Stats banner refreshes live rates every minute.

## Smoke

```
1. Draft workflow A: trigger(quote.sent) → send.email("Quote v1") → goal. Activate.
2. Clone to draft B: → swap email template → goal. Don't activate; save as draft.
3. On A's canvas → "Run A/B test" → pick B as sibling → 7d holdback → goal_conversion metric → start.
4. Both workflows now active; new quote.sent events 50/50-split.
5. After 7d, beat task picks winner; loser archived; banner closes.
6. Owner gets a notification: "Workflow B won the A/B test with X% vs Y%."
```

## Risks

- 50/50 hash determinism — using `hash((str(contact_id), str(workflow_id)))` modulo 2; document that hash collisions across Python versions could theoretically shift the split (mitigation: use SHA-256 + take first byte).
- Sample-size statistics — Z-test for proportions assumes binomial; for low conversion rates (<5%), n_min=50 may be inadequate. Document operators should pick `ab_test_min_runs_per_variant=200` for conversion rates under 5%.
- Auto-promote at midnight in operator's TZ vs server UTC — beat hourly is good enough; document the ~1h delay.

## Self-check (10 rules)

`core/workflows/`. ✓ org_id-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced. pack.yaml untouched. ✓ 14 files / ~800 lines — large but justified (full A/B feature). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 18 — A/B test entire workflows + winner selection
Files: 14
Verify: 50/50 split deterministic; sample size + p-value calc correct; winner auto-promoted after holdback; inconclusive extends holdback; banner shows live rates.
Tests: 12 pytest + 2 Jest.
Awaiting "proceed".
```
