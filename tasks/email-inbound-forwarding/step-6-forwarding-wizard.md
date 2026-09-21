# Step 6: Frontend — 3-step forwarding wizard + test-inbound watcher + provider guides

**Status:** Pending

## Goal

Complete the customer-facing wizard: pick provider → copy address → follow guide + wait for test-inbound bump. Provider guides sourced from Step 1 discovery.

## Files touched

- `APP/src/app/features/user/core/settings/email/forwarding-wizard.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/forwarding-wizard.service.ts`
- `APP/src/app/features/user/core/settings/email/provider-guides.ts` — hard-coded strings from Step 1
- `APP/src/app/features/user/core/settings/email/test-inbound-status.service.ts`
- `api/src/app/core/channel_endpoints/router.py` — extend with `GET /api/v1/channel-endpoints/{id}/test-inbound-status`

## What this step does

- Wizard component with 3 steps + navigation:
  - **Step 1 — Pick provider**: 6 cards (Gmail, Google Workspace, Outlook.com, Outlook 365, Zoho, Custom). Click → advance.
  - **Step 2 — Copy address**: large mono-font display of `f-<token>@in.karmcrm.com` with big Copy button (uses Angular CDK Clipboard). Label field to name the endpoint.
  - **Step 3 — Follow guide + test**: provider-specific step list rendered from `provider-guides.ts`. At bottom: "Send a test email to `f-<token>@in.karmcrm.com`" instruction + status badge. Poll `GET /channel-endpoints/{id}/test-inbound-status` every 5s. Badge states: `Waiting for test` → `Received!` (success, close-wizard button) → after 5min timeout: `Not received. Recheck settings.` with troubleshooting link.
- `provider-guides.ts`:
  ```typescript
  export const PROVIDER_GUIDES = {
    gmail: {
      title: 'Gmail (personal)',
      steps: [ /* verbatim from Step 1 DISCOVERY-NOTES.md */ ],
      docsUrl: 'https://support.google.com/mail/answer/10957',
    },
    // ... 5 more
  };
  ```
- Backend `GET /api/v1/channel-endpoints/{id}/test-inbound-status`:
  - Owner+Admin.
  - Org-scoped by JWT.
  - Loads endpoint + details.
  - Returns `{status: 'waiting' | 'received', last_inbound_at: <iso> | null}`.
  - `status='received'` when `last_inbound_at IS NOT NULL`.
- Wizard's endpoint-creation step calls `POST /api/v1/channel-endpoints/forwarded-address` with `{label, auto_create_contact=true}` — assignee defaults to current user; can be changed later in the list tab.

## Tests

**Backend:**
- `test_test_inbound_status_endpoint_returns_waiting_when_null`
- `test_test_inbound_status_endpoint_returns_received_after_bump`
- `test_test_inbound_status_scoped_by_org_id`
- `test_test_inbound_status_cross_org_returns_404`

**Frontend (Karma):**
- `test_wizard_step1_renders_6_provider_cards`
- `test_wizard_step1_click_provider_advances`
- `test_wizard_step2_shows_forwarding_address_with_copy_button`
- `test_wizard_step2_requires_label_before_advance`
- `test_wizard_step3_renders_provider_specific_steps_verbatim`
- `test_wizard_step3_polls_test_inbound_status_at_5s`
- `test_wizard_step3_success_after_bump_shows_confirm_state`
- `test_wizard_step3_timeout_at_5min_shows_recheck_prompt`
- `test_wizard_close_before_test_completes_still_creates_endpoint`

## Verification checklist

- [ ] All backend + Karma tests pass
- [ ] Prettier applied
- [ ] Lucide icons registered
- [ ] Manual smoke at Ajay's Workspace end-to-end: launch wizard → set Gmail forwarding rule → paste address → complete verification → send test → see "Received" badge → close
- [ ] `ng build` clean

## Self-check

- Rule 4: pass — server enforces Owner+Admin.
- Rule 2: pass — status endpoint org-scoped.
- Memory `feedback_prettier_on_write.md`: pass.
- Memory `feedback_lucide_icon_registry.md`: pass.

## Stop-and-report

Report Karma + backend test pass, end-to-end smoke output. **Track 3 done. Awaiting your "proceed" for Track 4 step 1.**
