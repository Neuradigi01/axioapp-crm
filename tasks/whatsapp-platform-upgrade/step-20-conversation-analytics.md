# Step 20 — Conversation analytics (volume, response time, outcomes, agent leaderboard)

**Goal:** Reporting → WhatsApp tab with message volume, response time distribution, outcome breakdown, and agent leaderboard. Manager dashboards that answer "is WhatsApp working?" and "who's responding fastest?"
**Status:** COMPLETED
**Depends on:** Step 14 (tags for outcome breakdown), Step 19 (AI vs human attribution).

---

## Scope

In-scope:
- Service `conversation_analytics.py` reading from existing `tbl_conversations` + `tbl_conversation_messages`.
- Endpoints:
  - `GET /api/v1/reports/whatsapp/volume?range=7d|30d|90d&granularity=day|hour` — sent / received / failed counts.
  - `GET /api/v1/reports/whatsapp/response-time?range=...&groupby=agent|team|channel` — median + p95 + distribution.
  - `GET /api/v1/reports/whatsapp/outcomes?range=...` — status distribution + tag breakdown.
  - `GET /api/v1/reports/whatsapp/agent-leaderboard?range=...` — sorted by response time + resolution count.
- Reuse existing reporting widget library (line chart, stat card, leaderboard table).
- WhatsApp section under Reporting page.
- Range picker + granularity toggle.
- Drilldown click → opens filtered conversation list.
- AI-vs-human attribution: split metrics; AI-only conversations excluded from human leaderboard; mixed attribute to last replier.
- Permission `whatsapp.analytics.read`.

Out of scope:
- Campaign analytics — Step 21.
- Cost dashboard — Step 21.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/reporting/whatsapp_analytics.py` | **NEW** |
| `API/src/app/core/reporting/router.py` | New endpoints |
| `API/src/app/core/reporting/module.py` | Register `whatsapp.analytics.read` + sub-page descriptor |
| `APP/.../reporting/whatsapp/whatsapp-reports-page.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/volume-widget.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/response-time-widget.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/outcomes-widget.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/agent-leaderboard.component.ts` | **NEW** |
| `APP/.../reporting/reports.service.ts` | New methods |
| `API/tests/reporting/test_whatsapp_analytics.py` | **NEW** |

**~10 files. ~600 lines.**

## Plan

1. Aggregation SQL: date_trunc bucketing + LIMIT 100 buckets per request.
2. Materialized view (`tbl_whatsapp_daily_rollup`) is **optional optimization** — defer unless org > 10K msg/month.
3. Response time helper: per-conversation time-to-first-staff-reply; ignore AI replies for human metrics.
4. Frontend: reuse existing widget library; range + granularity controls; drilldown link state.
5. Tests: each endpoint with happy + edge (empty range) + permission gate.

## DB changes / migrations

None required initially. Optional materialized view as follow-up if perf hits.

## Tests

8 pytest + 3 Jest.

## Smoke

```
1. Reporting → WhatsApp tab visible to user with whatsapp.analytics.read.
2. Volume widget shows last 7 days send/receive trends.
3. Response-time widget shows median + p95 per agent.
4. Outcomes widget shows resolved / lost / converted + tag breakdown.
5. Leaderboard sorts by response time; AI-only convos excluded.
6. Click a data point → filtered conversation list opens.
7. Sales-Junior without analytics.read → tab hidden.
```

## Risks

- 100K+ msg/month orgs: queries slow. Plan materialized view warming if hit.
- Timezone bugs in date bucketing — store UTC, convert at display.

## Self-check (10 rules)

All `core/reporting/`. ✓. Service-level org_id enforcement. ✓. No custom-field changes. ✓. Static widgets. ✓ N/A. Reporting module extended via descriptor. ✓. New permission registered. ✓. pack.yaml untouched. ✓. 10 files / ~600 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 20 — Conversation analytics
Files: 10
Verify: 4 widgets render real data; range/granularity work; drilldown links; permission gate.
Tests: 8 pytest + 3 Jest.
Next: Step 21 — campaign analytics + cost dashboard.
Awaiting "proceed".
```
