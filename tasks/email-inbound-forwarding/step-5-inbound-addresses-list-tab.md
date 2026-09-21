# Step 5: Frontend — Inbound addresses list tab + endpoint CRUD

**Status:** Pending

## Goal

Owner+Admin-facing list of `forwarded_address` endpoints per org. Endpoint create (launches wizard from Step 6), activate/deactivate, delete.

## Files touched

- `APP/src/app/features/user/core/settings/email/inbound-addresses-tab.component.ts` (+ html + scss)
- `APP/src/app/features/user/core/settings/email/inbound-addresses.service.ts`
- `APP/src/app/features/user/core/settings/tabs/email-settings-tab.component.ts` — register new tab
- `APP/src/app/features/user/core/settings/email/models.ts` — types

## What this step does

- Standalone component `inbound-addresses-tab`:
  - Header: "Inbound addresses", "+ Add forwarding address" button (launches wizard from Step 6).
  - Empty state: "Set up a forwarding address to receive mail sent to your existing support inbox".
  - Table columns: Label, Forwarding address (with copy button), Default assignee, Auto-create contact toggle, Last inbound (relative time), Status, Actions (overflow: rename, deactivate, delete).
  - Row-inline `auto_create_contact` toggle → PATCH endpoint.
  - Row-inline `default_assignee_user_id` dropdown → PATCH endpoint (populated from `GET /api/v1/users?in_org=true`).
  - Deactivate confirmation modal.
  - Delete confirmation modal with warning: "Any mail arriving at this address after deletion won't reach the CRM".
- Service:
  - `list()` → `GET /api/v1/channel-endpoints?endpoint_type=forwarded_address`
  - `create(payload)` → `POST /api/v1/channel-endpoints/forwarded-address` — wizard uses this
  - `update(id, payload)` → PATCH — label + toggles + assignee
  - `deactivate(id)` → POST deactivate
  - `remove(id)` → DELETE

## Tests (Karma)

- `test_list_renders_all_forwarded_address_endpoints`
- `test_list_shows_last_inbound_at_relative_time`
- `test_list_copy_button_copies_forwarding_address`
- `test_list_auto_create_toggle_patches_endpoint`
- `test_list_deactivate_button_confirms_before_call`
- `test_list_delete_button_shows_warning_before_confirm`
- `test_add_button_launches_wizard_component`

## Verification checklist

- [ ] Karma tests pass
- [ ] Prettier applied
- [ ] Lucide icons registered
- [ ] Manual smoke at Ajay's Workspace: create endpoint via API, confirm it shows in list, toggle auto-create, deactivate
- [ ] `ng build` clean

## Self-check

- Reuse: pass — reuses `<app-tabs>` primitive.
- Memory `feedback_reusable_code_lives_in_shared.md`: pass (per-page component).
- Memory `feedback_branding_crm_not_furnicrm.md`: pass.

## Stop-and-report

Report Karma pass, browser smoke output. **Awaiting your "proceed" for Step 6.**
