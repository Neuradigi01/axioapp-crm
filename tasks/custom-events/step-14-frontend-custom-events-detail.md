# Step 14 — Frontend detail page: Overview / Occurrences / Test fires / Workflows using this / How to fire tabs

**Goal:** the event detail page. Overview + 4 tabs (Occurrences federated primary+archive; Test fires from `_test_runs`; Workflows using this with reactivate prompt; How to fire with in-session pre-filled snippets, copy-only).
**Phase:** Custom Events track — step 14/17
**Depends on:** Steps 6-10, 12
**Status:** Pending

## Scope

**In-scope:**
- Route `/user/settings/custom-events/{id}`.
- Overview tab: name, label, category, is_active, created_by, occurrence count / test-fire count, "used in N workflows" summary.
- **Occurrences tab:** paginated table (fired_at, source, contact, payload preview truncated). Federated primary + archive when time range > 90d (uses backend `list_occurrences(org_id, event_id, since)` service function from README).
- **Test fires tab:** paginated from `tbl_custom_event_test_runs` (7-day retention). Shows fired_by_user, payload, rendered-actions preview (from dry-run engine).
- **Workflows using this tab:** list of workflows subscribing to this event's trigger. Owner sees a "Reactivate" prompt for previously-disabled workflows whose trigger still matches (from Step 9's `POST /custom-events/{id}/reactivate-workflows` endpoint). Prompt is opt-in — user selects which to enable.
- **How to fire tab:** 4 snippets (cURL, JS/Node, Python, Zapier steps) — key pre-filled ONLY in the browser session immediately after a create-key flow (SessionStorage token; auto-clears after 5min). Outside that window: shows `pk_live_YOUR_KEY_HERE` placeholder. Copy-to-clipboard button never renders full plaintext visibly. Includes HMAC-signing example when key has `hmac_required=true`.
- All payload previews rendered with `[textContent]` (never `[innerHTML]`) — XSS defense.

**Out of scope:**
- Docs + smoke (Step 15).

## Files to touch
- `APP/src/app/features/user/core/settings/custom-events/detail.page.ts/.html/.scss` (new).
- `APP/src/app/features/user/core/settings/custom-events/tabs/overview-tab.component.ts/.html` (new).
- `APP/src/app/features/user/core/settings/custom-events/tabs/occurrences-tab.component.ts/.html` (new).
- `APP/src/app/features/user/core/settings/custom-events/tabs/test-fires-tab.component.ts/.html` (new).
- `APP/src/app/features/user/core/settings/custom-events/tabs/workflows-tab.component.ts/.html` (new — with reactivate prompt).
- `APP/src/app/features/user/core/settings/custom-events/tabs/how-to-fire-tab.component.ts/.html` (new — copy-only snippets).
- `APP/src/app/features/user/core/settings/custom-events/custom-events.service.ts` (modified — occurrence + test-run + workflows-using endpoints).
- Playwright specs.

## Plan
1. Detail page shell + tab routing.
2. Each tab component.
3. Federated occurrences query (backend needs `list_occurrences(since)` service function — add if not present).
4. Playwright covering all 5 tabs.

## Tests to add
- Playwright: occurrences tab pagination + filter by date.
- Playwright: occurrences tab crosses into archive when `since` > 90d.
- Playwright: test fires tab shows dry-run output, not live occurrences.
- Playwright: workflows tab reactivate prompt appears for previously-disabled workflows.
- Playwright: how-to-fire tab pre-fills key only in-session post-create.
- Playwright: outside the window, shows placeholder.
- Playwright: copy button copies to clipboard without visible plaintext.

## Verification checklist
- Frontend: prettier + eslint clean.
- Frontend: manual walk of all 5 tabs.
- Backend: `list_occurrences(since)` service function tested.

## Self-check
- [ ] Rule N/A / clean.
- [ ] Rule 8: ~10 files — at limit; split occurrences/test-fires/workflows into separate PRs if larger.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
