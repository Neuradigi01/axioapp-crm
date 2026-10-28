# Step 10 — Per-template performance card

**Goal:** Surface per-template metrics (sent / delivered / read / replied / click-through / failed) over selectable time ranges, with failure breakdown. Customer sees which templates perform and which to retire.
**Status:** COMPLETED
**Depends on:** Step 9 (templates UI exists to host the card).

---

## Scope

In-scope:
- Backend aggregation endpoint `GET /api/v1/whatsapp/templates/{id}/performance?range=7d|30d|90d`:
  - sent, delivered, read, replied, click_through (button taps from Step 6's interactive messages), failed (with top failure reasons grouped)
  - delivery_rate, read_rate, reply_rate (computed)
- Source: aggregate from `tbl_campaign_messages` + `tbl_conversation_messages` where `template_id = X`.
- Optimization: index on `(template_id, created_at)` if not present.
- Frontend: small sparkline + sent count on each row of the templates list (Step 9 list view extension).
- Template detail panel: stat cards (Sent / Delivered / Read / Replied) + line chart over selected range + failure breakdown table.
- "Used in N campaigns" link → filters campaigns list.

Out of scope:
- Cross-template comparison — Step 21 (campaign analytics) covers leaderboard.
- Cost estimation per template — Step 21 (cost dashboard) covers.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/templates_analytics.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/templates_router.py` | Extend with `/{id}/performance` route |
| `API/alembic/versions/<ts>_template_id_index.py` | **NEW** index (if not present) |
| `APP/.../whatsapp/templates/template-performance.component.ts` | **NEW** stat cards + chart + failure table |
| `APP/.../whatsapp/templates/templates-page.component.ts` | Extend list row with sparkline + sent count |
| `API/tests/integrations/test_template_performance.py` | **NEW** |

**~6 files. ~350 lines.**

## Plan

1. Aggregation service: SQL with date_trunc bucketing; cap result to ~100 buckets per request.
2. Failure reason taxonomy: map Meta error codes to friendly buckets (rate-limited, opted-out, invalid number, template paused, other).
3. Frontend stat cards reuse existing reporting widget library.
4. Sparkline component: tiny SVG (60×24px) with last 7-day trend.
5. Empty state: "No data yet — send this template in a campaign to see metrics."
6. Tests: 4 cases including empty-state, full-range, failure-grouping, permission gate.

## DB changes / migrations

Optional `(template_id, created_at)` composite index on `tbl_campaign_messages`. Conditional.

## Tests

4 pytest + 2 Jest.

## Smoke

```
1. Send a campaign of 50 messages using template "marketing_v1".
2. Open templates list → row shows 50 sent + small sparkline.
3. Click template → detail panel → stat cards show 50/47/30/8 (sent/delivered/read/replied).
4. Failure breakdown shows 3 invalid numbers + 0 rate-limited.
5. Range toggle: 7d / 30d / 90d updates chart.
6. "Used in N campaigns" link → filter applied on campaigns list.
```

## Risks

- Big orgs with 100K+ messages in range: query slow; add LIMIT or materialized view.
- Click-through count depends on Step 6's button reply event capture being correct.

## Self-check (10 rules)

All `core/integrations/whatsapp/`. ✓. org_id + RLS. ✓. No custom-field changes. ✓. Static cards. ✓ N/A. No new registry/permission. ✓. pack.yaml untouched. ✓. 6 files / ~350 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 10 — Template performance card
Files: 6
Verify: per-template stats + sparkline + range toggle + failure breakdown.
Tests: 4 pytest + 2 Jest.
Phase 3 (Templates) complete. Next: Step 11 — business profile editor.
Awaiting "proceed".
```
