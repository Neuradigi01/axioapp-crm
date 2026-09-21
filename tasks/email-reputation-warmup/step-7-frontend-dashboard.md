# Step 7: Frontend — Reputation dashboard tab + per-envelope cards

**Status:** Pending

## Goal

Owner-facing reputation surface. Per-envelope card: warmup progress bar, 24h metrics (delivered / bounced / complained / rates), state badge, blocked-until countdown, amber warning banner when demoted or blocked.

## Files touched

- `APP/src/app/features/user/core/settings/email/reputation-dashboard-tab.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/envelope-reputation-card.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/reputation.service.ts`
- `APP/src/app/features/user/core/settings/tabs/email-settings-tab.component.ts` — register tab
- `api/src/app/core/email/reputation/router.py` — dashboard endpoint

## What this step does

- Backend endpoint:
  - `GET /api/v1/reputation/dashboard` — Owner-only.
  - Returns list of `EnvelopeReputationOut`:
    - `envelope_type`, `domain_id` (nullable), `domain_string` (populated for own_domain).
    - `warmup_stage`, `stage_cap`, `next_stage_cap`, `stage_progress_pct`.
    - `daily_sent, daily_cap`.
    - `delivered_24h, bounced_24h, complained_24h, unsubscribed_24h`.
    - `complaint_rate, bounce_rate`.
    - `reputation_state, blocked_until` (nullable).
- Dashboard component:
  - Header: "Sending reputation".
  - Grid of `<app-envelope-reputation-card>` — one per envelope.
- Card component:
  - Envelope name + type badge (Platform / Own domain).
  - Warmup progress bar (green/amber/red by state).
  - "Daily sent: 123 / 1000" progress bar.
  - 4 metric tiles: delivered, bounced, complained, unsubscribed (with rates).
  - State badge: OK (green) / Warned (amber) / Blocked (red).
  - Blocked-until countdown (dynamic tick).
  - Amber standard warning banner when state = warned or blocked.
- Service: `list()` → `GET /api/v1/reputation/dashboard`, 30s auto-refresh.

## Tests

**Backend:**
- `test_dashboard_endpoint_owner_only`
- `test_dashboard_endpoint_returns_row_per_envelope`
- `test_dashboard_endpoint_scoped_by_org`
- `test_dashboard_endpoint_computes_rates_from_24h_counters`

**Frontend (Karma):**
- `test_dashboard_renders_platform_from_card`
- `test_dashboard_renders_one_card_per_verified_own_domain`
- `test_card_shows_warmup_progress_bar`
- `test_card_blocked_until_shows_countdown`
- `test_card_warned_state_shows_amber_banner`
- `test_card_metric_tiles_render_delivered_bounced_complained_unsubscribed`

## Verification checklist

- [ ] All 10 tests pass
- [ ] Prettier applied
- [ ] Lucide icons registered
- [ ] Manual smoke at Ajay's Workspace: send a batch of emails via campaign, observe counters bump on dashboard within 30s
- [ ] `ng build` clean

## Self-check

- Rule 4: pass — Owner-only enforced server-side.
- Rule 2: pass — org-scoped.
- Memory `feedback_standard_warning_banner_pattern.md`: pass.
- Memory `feedback_prettier_on_write.md`: pass.

## Stop-and-report

Report test pass, smoke output, screenshot of dashboard. **Track 4 done. Awaiting your "proceed" for Track 5 step 1.**
