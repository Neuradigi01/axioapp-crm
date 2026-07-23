# Step 5 — Matched-events preview count (Phase 2)

**Goal:** Under the builder's sentence preview, render a small line: `This condition would have matched N events in the last 7 days.` Powered by a new endpoint that scans past trigger runs + the audit log with the customer's draft condition applied, returning the count without dispatching anything. Purely informational — confirms intent before Save.
**Status:** Pending (Phase 2 — ships AFTER step-4).
**Depends on:** Step 4 (Advanced-mode legacy handling stable so preview works for legacy rules too).

---

## Scope

In-scope:

- `POST /api/v1/automations/event-types/{event_type}/preview-matches` — new endpoint.
  - Body: `{conditions: dict, window_days: int = 7}`. `conditions` is the same AST shape the editor emits.
  - Server pulls the last `window_days` of events for this `event_type` from a payload-persisted source and runs the same `conditions.evaluate(...)` used by the live dispatcher against each payload. Counts matches.
  - Payload source, in priority order:
    1. `tbl_automation_runs.event_payload` filtered by `(org_id, event_type, scheduled_at >= now() - window_days)` — cheapest, already indexed by `(org_id, trigger_id, scheduled_at)`. Downside: only carries events that actually triggered ≥1 existing automation, so a fresh event type with no active triggers returns `0` even if the event is firing (undercount for that edge case).
    2. `tbl_audit_log` events filtered by `(org_id, event_type, occurred_at >= ...)` — falls back here when the runs table is empty for this type. Not every domain module writes to the audit log yet (`tasks/audit-log/` is Phase 2 itself), so this branch is best-effort.
  - Response: `{matched: int, scanned: int, window_days: int, source: "runs" | "audit_log" | "none"}`. `source == "none"` signals the frontend to render a "No historical events available for preview" grey line instead of "matched 0".
  - Errors: `400 invalid_conditions` if `conditions.validate(...)` raises; `404 event_not_found` if the event isn't in the catalog; feature-flag gate returns `404 friendly_builder_disabled` when off.
  - Perf cap: `LIMIT 500` on the scan query. If the org has >500 events in the window, the response includes `truncated: true` and the frontend shows "at least N matches" instead of an exact count.
  - Cache-Control: `private, max-age=15` — the preview updates as the operator authors, so a longer cache would show stale numbers.
  - Rate limit: 30/min per user (heavier than the field-values endpoint because it scans rows).
- Frontend: `condition-builder.component.ts` adds a debounced preview trigger. 500 ms after the AST last changed, fire `automations-api.previewMatches(event, conditions)`. Loading spinner → count text.
  - Zero-count render: "This condition would not have matched any events in the last 7 days. Double-check the field labels + values."
  - Truncated render: "Matched at least 500 events in the last 7 days. Consider tightening the filter to a smaller window."
  - Source-none render: "No historical events available for preview" in muted grey.
  - Error render: "Preview unavailable" — non-fatal, doesn't block Save.
- Feature flag: `automation_conditions.matched_events_preview_enabled` — a separate flag from the main `friendly_builder_enabled` so this Phase-2 preview can be dark-launched independently.
- Pytest — 6 cases (below). Jasmine — 3 cases (debounce, zero-count copy, truncated copy).

Out of scope:
- Suggesting a tighter filter automatically.
- Per-event drill-down list of which past events matched.
- Scheduled events (`lead.stale_30d`, `contact.birthday`, ...) — these don't sit in an event-source table the same way. The preview returns `source: "none"` for time-based events; a suggestion for a later step is to pre-compute a synthetic sample from the current DB state (e.g. "count leads that would fire the 30-day stale sweep tomorrow").

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/router.py` | edit — add preview-matches endpoint |
| `API/src/app/core/automation/service.py` | edit — add `preview_matches_service(...)` |
| `API/src/app/core/automation/data_access.py` | edit — add `list_recent_event_payloads(...)` (runs table) + `list_recent_audit_events(...)` (audit table) |
| `API/src/app/core/automation/schemas.py` | edit — `PreviewMatchesRequest` + `PreviewMatchesResponse` |
| `API/src/app/shared/feature_flags.py` | edit — add second flag |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.ts` | edit — debounced preview + render branches |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.html` | edit — preview line markup |
| `APP/src/app/features/user/core/automations/automations-api.service.ts` | edit — `previewMatches(...)` method |
| `API/tests/automation/test_preview_matches.py` | **NEW** — 6 pytest cases |

**~9 files. ~500 lines.**

## Plan

1. DAL: two read helpers, tenant-scoped.
2. Service: pick the source, run the evaluator, count matches, respect the 500-row cap.
3. Router: parse body, gate on flag, wrap exceptions.
4. Frontend debounce (rxjs `debounceTime(500)` on the AST signal via `toObservable`), swap the render.
5. Tests + smoke.

## DB changes / migrations

None — reads existing tables.

## Tests

- `test_preview_returns_count_from_runs_source`.
- `test_preview_falls_back_to_audit_when_runs_empty`.
- `test_preview_returns_source_none_when_neither_has_data`.
- `test_preview_respects_500_row_cap_returns_truncated_true`.
- `test_preview_rejects_invalid_conditions_400`.
- `test_preview_flag_off_returns_404`.

## Smoke

```
1. Flag on. Ajay's org has 3 lead.created events in the last 7 days,
   2 with source="widget", 1 with source="google_ads".
2. Builder: event=lead.created, rule=source in [widget].
   → preview line: "This condition would have matched 2 events in the last 7 days."
3. Change to source in [google_ads] → preview updates after 500ms debounce to "1 event".
4. Change to source in [tiktok] → "would not have matched any events... Double-check ...".
5. Switch to appointment.reminder_24h → preview shows "No historical events available for preview".
```

## Risks

- **Undercount for fresh event types.** A brand-new event with no existing triggers won't be in `tbl_automation_runs`. Mitigated by the audit-log fallback + the honest `source: "none"` render for events neither source has.
- **Perf on wide scans.** The 500-row cap + 15s cache + per-user rate limit bound the cost. Add an index on `(org_id, event_type, scheduled_at DESC)` if EXPLAIN shows a seq scan on a big-org test DB.
- **Confusing sentence-preview interaction.** Two lines under the builder — sentence preview + count. Space out with a divider so the customer reads them as distinct.

## Self-check (10 rules)

`core/automation/`. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions gated (same PERM_READ). ✓ pack.yaml untouched. ✓ 9 files / ~500 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 5 — Matched-events preview count (Phase 2)
Files: 9
Verify: preview line renders correct count for authored draft against Ajay's org.
Tests: 6 pytest + 3 Jasmine.
Awaiting "proceed".
```
